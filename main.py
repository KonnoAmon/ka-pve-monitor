import os
import json
import psutil
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

def bytes_to_gb(bytes_value):
    return round(bytes_value / (1024 ** 3), 1)

# --- 核心：数据获取逻辑提取 ---
def get_system_status():
    data = {
        "pve": {"cpu": 0, "ram_percent": 0, "ram_used": 0, "ram_total": 0, "online": False},
        "docker": {"cpu": 0, "ram_percent": 0, "ram_used": 0, "ram_total": 0},
        "vms": [],
        "containers": []
    }
    
    # 1. PVE 数据
    pve = get_pve_client()
    if pve:
        try:
            nodes = pve.nodes.get()
            if nodes:
                node_name = nodes[0]['node']
                node_status = pve.nodes(node_name).status.get()
                
                data['pve']['online'] = True
                data['pve']['cpu'] = round(node_status.get('cpu', 0) * 100, 1)
                mem_total = node_status.get('memory', {}).get('total', 1)
                mem_used = node_status.get('memory', {}).get('used', 0)
                data['pve']['ram_total'] = bytes_to_gb(mem_total)
                data['pve']['ram_used'] = bytes_to_gb(mem_used)
                data['pve']['ram_percent'] = round((mem_used / mem_total) * 100, 1)

                for node in nodes:
                    for vm in pve.nodes(node['node']).qemu.get():
                        data['vms'].append({
                            "id": vm['vmid'],
                            "name": vm.get('name', 'Unknown'),
                            "status": vm.get('status', 'unknown'),
                            "node": node['node']
                        })
        except: pass

    # 2. Docker/Local 数据
    try:
        data['docker']['cpu'] = psutil.cpu_percent(interval=None) # interval=None 非阻塞
        mem = psutil.virtual_memory()
        data['docker']['ram_total'] = bytes_to_gb(mem.total)
        data['docker']['ram_used'] = bytes_to_gb(mem.used)
        data['docker']['ram_percent'] = mem.percent

        d_client = get_docker_client()
        if d_client:
            for c in d_client.containers.list(all=True):
                data['containers'].append({"id": c.short_id, "name": c.name, "status": c.status})
    except: pass
    
    return data

# --- 路由 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = load_config()
    if not config: return RedirectResponse(url="/settings", status_code=302)
    
    # 首次加载时获取一次数据
    data = get_system_status()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "vms": data['vms'], 
        "containers": data['containers'], 
        "stats": data,
        "errors": []
    })

# 新增：专门用于前端轮询数据的 JSON 接口
@app.get("/api/monitor")
async def api_monitor():
    return JSONResponse(get_system_status())

# ... (保持 settings 和 control API 不变) ...
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