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
import random
import base64
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable  # 需要保留这个导入，因为用于获取 GIT_TOKEN
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        # 过滤掉非 IP 格式的行
        lines = [line.strip() for line in lines if is_valid_proxy(line)]
        proxies.extend(lines)
        print(f"Loaded {len(lines)} proxies from {url}")
        for line in lines:
            proxy_url_infos[line] = url
    print(f"Total {len(proxies)} proxies loaded")
    random.shuffle(proxies)
    return proxies, proxy_url_infos

def is_valid_proxy(proxy):
    # 简单的 IP 格式验证
    parts = proxy.split(':')
    if len(parts) != 2:
        return False
    ip, port = parts
    return ip.count('.') == 3 and port.isdigit()

def check_proxy(proxy_url, proxy_url_infos):
    """
    使用 requests 检查代理是否可用
    """
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"{now} Checking {proxy_url}")
        target_url = 'https://wxsports.ydmap.cn/srv200/api/pub/basic/getConfig'
        
        proxies = {
            'http': f'http://{proxy_url}',
            'https': f'http://{proxy_url}'
        }
        
        response = requests.get(
            target_url,
            proxies=proxies,
            timeout=3,
            verify=False  # 忽略 SSL 验证
        )
        
        response_text = response.text
        
        if response.status_code == 200 and ("html" in response_text or 
            ('"code":-1' in response_text and "签名错误" in response_text)):
            print(f"{now} [OK] {proxy_url} from {proxy_url_infos.get(proxy_url)}")
            return proxy_url
            
    except Exception as error:
        # print(str(error))
        pass
    return None

def update_proxy_file(filename, available_proxies):
    # 确保文件内容被正确初始化
    with open(filename, "w") as file:
        for proxy in available_proxies:
            file.write(proxy + "\n")
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

def task_check_proxies():
    """
    主要检查代理的任务函数
    """
    download_file()
    
    proxies, proxy_url_infos = generate_proxies()
    print(f"start checking {len(proxies)} proxies")
    
    available_proxies = []
    for proxy in proxies:
        if check_proxy(proxy, proxy_url_infos):
            available_proxies.append(proxy)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{now} Available proxies: {len(available_proxies)}")
            
            update_proxy_file(FILENAME, available_proxies)
            upload_file_to_github(FILENAME)
    
    print("check end.")

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
        'message': 'Update proxy list by airflow',
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
    dag_id='HTTPS可用代理巡检_ydmap',
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
    task_check_proxies()

# 创建任务
check_proxies_task = PythonOperator(
    task_id='check_proxies',
    python_callable=run_proxy_checker,
    dag=dag,
)

# 设置任务依赖关系
check_proxies_task
