import os
import json
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

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

templates = Jinja2Templates(directory="templates")

# --- 辅助函数：读写配置 ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return None

def save_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f)

# --- 辅助函数：获取客户端 ---
def get_pve_client():
    config = load_config()
    if not config:
        return None
    try:
        return ProxmoxAPI(
            config['pve_host'], 
            user=config['pve_user'], 
            token_name=config['pve_token_name'], 
            token_value=config['pve_token_value'], 
            verify_ssl=False, 
            timeout=2
        )
    except Exception as e:
        print(f"PVE Client Init Error: {e}")
        return None # 连接失败返回None，由调用方处理

def get_docker_client():
    try:
        return docker.from_env()
    except:
        return None

# --- 路由定义 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """主仪表盘"""
    config = load_config()
    
    # 如果没有配置，强制跳转到设置页
    if not config:
        return RedirectResponse(url="/settings", status_code=302)

    vms = []
    containers = []
    errors = []

    # 1. 获取 PVE 数据
    pve = get_pve_client()
    if pve:
        try:
            nodes = pve.nodes.get()
            for node in nodes:
                for vm in pve.nodes(node['node']).qemu.get():
                    vms.append({
                        "id": vm['vmid'],
                        "name": vm.get('name', 'Unknown'),
                        "status": vm.get('status', 'unknown'),
                        "node": node['node']
                    })
        except Exception as e:
            errors.append(f"PVE连接失败: 请检查设置页配置 ({str(e)})")
    else:
        errors.append("无法初始化PVE连接，配置可能错误")

    # 2. 获取 Docker 数据
    try:
        d_client = get_docker_client()
        if d_client:
            for c in d_client.containers.list(all=True):
                containers.append({
                    "id": c.short_id,
                    "name": c.name,
                    "status": c.status
                })
        else:
            errors.append("无法连接本地Docker Socket")
    except Exception as e:
        errors.append(f"Docker错误: {str(e)}")

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "vms": vms, 
        "containers": containers,
        "errors": errors
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置页面"""
    config = load_config() or {}
    return templates.TemplateResponse("settings.html", {"request": request, "config": config})

@app.post("/settings")
async def settings_save(
    request: Request,
    pve_host: str = Form(...),
    pve_user: str = Form(...),
    pve_token_name: str = Form(...),
    pve_token_value: str = Form(...)
):
    """保存设置"""
    data = {
        "pve_host": pve_host,
        "pve_user": pve_user,
        "pve_token_name": pve_token_name,
        "pve_token_value": pve_token_value
    }
    save_config(data)
    return RedirectResponse(url="/", status_code=302)

# --- 控制 API (复用之前的逻辑) ---
@app.post("/api/pve/{node}/{vmid}/{action}")
async def pve_control(node: str, vmid: int, action: str):
    pve = get_pve_client()
    if not pve: raise HTTPException(status_code=500, detail="PVE未配置")
    try:
        getattr(pve.nodes(node).qemu(vmid).status, action).post()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)