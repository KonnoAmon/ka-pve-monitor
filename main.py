import os
import json
import psutil # 新增
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from proxmoxer import ProxmoxAPI
import docker
import uvicorn

app = FastAPI()

# --- 配置存储路径 ---
DATA_DIR = "/app/data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

templates = Jinja2Templates(directory="templates")

# --- 辅助函数 ---
def load_config():
    if not os.path.exists(CONFIG_FILE): return None
    try:
        with open(CONFIG_FILE, 'r') as f: return json.load(f)
    except: return None

def save_config(data):
    with open(CONFIG_FILE, 'w') as f: json.dump(data, f)

def get_pve_client():
    config = load_config()
    if not config: return None
    try:
        return ProxmoxAPI(
            config['pve_host'], user=config['pve_user'], 
            token_name=config['pve_token_name'], token_value=config['pve_token_value'], 
            verify_ssl=False, timeout=2
        )
    except: return None

def get_docker_client():
    try: return docker.from_env()
    except: return None

# 格式化字节单位 (比如把 1024000 转成 1GB)
def bytes_to_gb(bytes_value):
    return round(bytes_value / (1024 ** 3), 1)

# --- 路由 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = load_config()
    if not config: return RedirectResponse(url="/settings", status_code=302)

    vms = []
    containers = []
    errors = []
    
    # 1. 监控数据初始化
    stats = {
        "pve": {"cpu": 0, "ram_percent": 0, "ram_used": 0, "ram_total": 0, "online": False},
        "docker": {"cpu": 0, "ram_percent": 0, "ram_used": 0, "ram_total": 0}
    }

    # 2. 获取 PVE 数据 & 资源状态
    pve = get_pve_client()
    if pve:
        try:
            nodes = pve.nodes.get()
            # 默认只取第一个节点的状态作为 PVE 整体状态
            if nodes:
                node_name = nodes[0]['node']
                node_status = pve.nodes(node_name).status.get()
                
                # PVE 资源计算
                stats['pve']['online'] = True
                stats['pve']['cpu'] = round(node_status.get('cpu', 0) * 100, 1) # API返回的是 0.05 代表 5%
                mem_total = node_status.get('memory', {}).get('total', 1)
                mem_used = node_status.get('memory', {}).get('used', 0)
                stats['pve']['ram_total'] = bytes_to_gb(mem_total)
                stats['pve']['ram_used'] = bytes_to_gb(mem_used)
                stats['pve']['ram_percent'] = round((mem_used / mem_total) * 100, 1)

                # 获取虚拟机列表
                for node in nodes:
                    for vm in pve.nodes(node['node']).qemu.get():
                        vms.append({
                            "id": vm['vmid'],
                            "name": vm.get('name', 'Unknown'),
                            "status": vm.get('status', 'unknown'),
                            "node": node['node']
                        })
        except Exception as e:
            errors.append(f"PVE连接失败: {str(e)}")
    else:
        errors.append("PVE未连接")

    # 3. 获取本机(Docker宿主机) 资源状态
    try:
        # psutil 获取的是容器内的视角，如果为了获取宿主机，需要挂载 /proc (后面docker-compose会讲)
        # 这里演示获取本机/容器的状态
        stats['docker']['cpu'] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        stats['docker']['ram_total'] = bytes_to_gb(mem.total)
        stats['docker']['ram_used'] = bytes_to_gb(mem.used)
        stats['docker']['ram_percent'] = mem.percent

        d_client = get_docker_client()
        if d_client:
            for c in d_client.containers.list(all=True):
                containers.append({"id": c.short_id, "name": c.name, "status": c.status})
    except Exception as e:
        errors.append(f"Docker/系统监控失败: {str(e)}")

    return templates.TemplateResponse("index.html", {
        "request": request, "vms": vms, "containers": containers, "errors": errors, "stats": stats
    })

# ... (settings 和 api 的路由保持不变，为了节省篇幅我省略了，请保留你原来的代码) ...
# 为了保证完整性，你需要把原来 main.py 下面的 /settings 和 /api 相关的代码原样粘在下面
# --------------------------------------------------------------------------
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    config = load_config() or {}
    return templates.TemplateResponse("settings.html", {"request": request, "config": config})

@app.post("/settings")
async def settings_save(
    request: Request,
    pve_host: str = Form(...), pve_user: str = Form(...),
    pve_token_name: str = Form(...), pve_token_value: str = Form(...)
):
    save_config({"pve_host": pve_host, "pve_user": pve_user, "pve_token_name": pve_token_name, "pve_token_value": pve_token_value})
    return RedirectResponse(url="/", status_code=302)

@app.post("/api/pve/{node}/{vmid}/{action}")
async def pve_control(node: str, vmid: int, action: str):
    pve = get_pve_client()
    if not pve: raise HTTPException(status_code=500, detail="PVE未配置")
    try:
        getattr(pve.nodes(node).qemu(vmid).status, action).post()
        return {"status": "success"}
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/docker/{cid}/{action}")
async def docker_control(cid: str, action: str):
    client = get_docker_client()
    if not client: raise HTTPException(status_code=500, detail="Docker未连接")
    try:
        container = client.containers.get(cid)
        if action == "start": container.start()
        elif action == "stop": container.stop()
        elif action == "restart": container.restart()
        return {"status": "success"}
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)