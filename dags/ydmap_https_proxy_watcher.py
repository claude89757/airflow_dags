#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024-03-20 02:35:46
@Author  : claude89757
@File    : ydmap_https_proxy_watcher.py
@Description : Airflow DAG for checking and updating HTTPS proxies
"""

# 标准库导入
import os
import sys
import time
import random
import base64
import asyncio
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# 第三方库导入
import requests
import aiohttp
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

# 常量定义
FILENAME = "/tmp/isz_https_proxies.txt"

def generate_proxies():
    """
    获取待检查的代理列表
    """
    urls = [
        "https://github.com/roosterkid/openproxylist/raw/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/yoannchb-pro/https-proxies/main/proxies.txt",
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
        "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
    ]
    proxies = []

    proxy_url_infos = {}
    for url in urls:
        print(f"getting proxy list for {url}")
        response = requests.get(url)
        text = response.text.strip()
        lines = text.split("\n")
        lines = [line.strip() for line in lines]
        proxies.extend(lines)
        print(f"Loaded {len(lines)} proxies from {url}")
        for line in lines:
            proxy_url_infos[line] = url
    print(f"Total {len(proxies)} proxies loaded")
    random.shuffle(proxies)
    return proxies, proxy_url_infos

class ProxyCheckerConfig:
    def __init__(self):
        self.initial_concurrency = 50
        self.max_concurrency = 100
        self.min_concurrency = 10
        self.success_threshold = 0.3
        self.check_interval = 60
        self.current_concurrency = self.initial_concurrency
        
        self.total_checked = 0
        self.success_count = 0
        self.last_adjust_time = time.time()

    def adjust_concurrency(self):
        """动态调整并发数"""
        current_time = time.time()
        if current_time - self.last_adjust_time < self.check_interval:
            return

        if self.total_checked == 0:
            return

        success_rate = self.success_count / self.total_checked
        
        if success_rate > self.success_threshold:
            self.current_concurrency = min(
                self.current_concurrency + 10, 
                self.max_concurrency
            )
        else:
            self.current_concurrency = max(
                self.current_concurrency - 5,
                self.min_concurrency
            )
            
        print(f"调整并发数到: {self.current_concurrency}, 成功率: {success_rate:.2%}")
        self.last_adjust_time = current_time
        self.total_checked = 0
        self.success_count = 0

async def check_proxy_async(proxy_url, proxy_url_infos, session, config):
    """异步检查代理是否可用"""
    try:
        # print(f"正在检查 {proxy_url}")
        target_url = 'https://wxsports.ydmap.cn/srv200/api/pub/basic/getConfig'
        
        async with session.get(
            target_url,
            proxy=f"http://{proxy_url}",
            timeout=aiohttp.ClientTimeout(total=3)
        ) as response:
            response_text = await response.text()
            
            config.total_checked += 1
            
            if response.status == 200 and ("html" in response_text or "签名错误" in response_text):
                print(f"[OK] {proxy_url} from {proxy_url_infos.get(proxy_url)}")
                config.success_count += 1
                return proxy_url
                
    except Exception as error:
        # print(f"代理 {proxy_url} 检查失败: {str(error)}")
        pass
    
    return None

def update_proxy_file(filename, available_proxies):
    try:
        with open(filename, "r") as file:
            existing_proxies = file.readlines()
    except FileNotFoundError:
        existing_proxies = ""

    existing_proxies = [proxy.strip() for proxy in existing_proxies]
    new_proxies = [proxy for proxy in available_proxies if proxy not in existing_proxies]

    if new_proxies:
        with open(filename, "a") as file:
            for proxy in new_proxies:
                file.write(proxy + "\n")

    with open(filename, "r") as file:
        lines = file.readlines()

    if len(lines) > 400:
        with open(filename, "w") as file:
            file.writelines(lines[200:])

async def task_check_proxies_async():
    config = ProxyCheckerConfig()
    
    download_file()
    
    proxies, proxy_url_infos = generate_proxies()
    print(f"开始检查 {len(proxies)} 个代理")
    
    available_proxies = []
    
    async with aiohttp.ClientSession() as session:
        while proxies:
            config.adjust_concurrency()
            
            batch_proxies = proxies[:config.current_concurrency]
            proxies = proxies[config.current_concurrency:]
            
            tasks = [
                check_proxy_async(proxy, proxy_url_infos, session, config)
                for proxy in batch_proxies
            ]
            
            results = await asyncio.gather(*tasks)
            
            valid_proxies = [p for p in results if p]
            if valid_proxies:
                available_proxies.extend(valid_proxies)
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"{now} 可用代理数量: {len(available_proxies)}")
                
                update_proxy_file(FILENAME, available_proxies)
                upload_file_to_github(FILENAME)

    print("检查完成")

def upload_file_to_github(filename):
    token = Variable.get('GIT_TOKEN')
    repo = 'claude89757/free_https_proxies'
    url = f'https://api.github.com/repos/{repo}/contents/{FILENAME}'

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    with open(FILENAME, 'rb') as file:
        content = file.read()
    data = {
        'message': f'Update proxy list by scf',
        'content': base64.b64encode(content).decode('utf-8'),
        'sha': get_file_sha(url, headers)
    }
    response = requests.put(url, headers=headers, json=data)
    if response.status_code == 200:
        print("File uploaded successfully.")
    else:
        print("Failed to upload file:", response.status_code, response.text)

def download_file():
    try:
        url = 'https://raw.githubusercontent.com/claude89757/free_https_proxies/main/free_https_proxies.txt'
        response = requests.get(url)
        response.raise_for_status()

        with open(FILENAME, 'wb') as file:
            file.write(response.content)
        print(f"File downloaded and saved to {FILENAME}")
    except requests.RequestException as e:
        print(f"Failed to download the file: {e}")

def get_file_sha(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()['sha']
    return None

# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(minutes=30),
}

# 定义DAG
dag = DAG(
    dag_id='ydmap_https_proxy_watcher',
    default_args=default_args,
    description='A DAG to check and update HTTPS proxies',
    schedule_interval='*/30 * * * *',
    start_date=datetime(2024, 1, 1),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    catchup=False,
    tags=['proxy', 'ydmap'],
)

def run_proxy_checker():
    """Airflow任务的入口点"""
    asyncio.run(task_check_proxies_async())

# 创建任务
check_proxies_task = PythonOperator(
    task_id='check_proxies',
    python_callable=run_proxy_checker,
    dag=dag,
)

# 设置任务依赖关系
check_proxies_task
