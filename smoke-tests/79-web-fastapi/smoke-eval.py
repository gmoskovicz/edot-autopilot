#!/usr/bin/env python3
"""Eval test: Web — FastAPI Order API. Run: cd smoke-tests && python3 79-web-fastapi/smoke-eval.py"""
import os, sys, shutil, subprocess, tempfile, time, urllib.request
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT","").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY","")
if not ENDPOINT or not API_KEY: print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set"); sys.exit(0)
SVC="79-web-fastapi"; PORT=16079; FIXTURE_DIR=os.path.join(os.path.dirname(__file__),"fixtures","blank-fastapi-orders")
CLAUDE_MD=os.path.join(os.path.dirname(__file__),"../../CLAUDE.md")
if not os.path.exists(CLAUDE_MD): CLAUDE_MD=os.path.join(os.path.dirname(__file__),"../../../CLAUDE.md")
CHECKS: list[tuple[str,bool,str]]=[]
def check(name,ok,detail=""): CHECKS.append(("PASS" if ok else "FAIL",name,detail))
print(f"\n{'='*62}\nEDOT-Autopilot | {SVC}\n{'='*62}")
print(f"  Fixture: blank-fastapi-orders (FastAPI, no OTel)  |  port: {PORT}\n")
claude_bin=shutil.which("claude")
check("claude CLI installed",claude_bin is not None); check("CLAUDE.md exists",os.path.exists(CLAUDE_MD)); check("Fixture exists",os.path.isdir(FIXTURE_DIR))
if not claude_bin or not os.path.exists(CLAUDE_MD) or not os.path.isdir(FIXTURE_DIR): [print(f"  [{s}] {n}") for s,n,_ in CHECKS]; sys.exit(1)
tmpdir=tempfile.mkdtemp(prefix="edot-autopilot-fastapi-")
proc=None
try:
    shutil.copytree(FIXTURE_DIR,tmpdir,dirs_exist_ok=True); shutil.copy2(CLAUDE_MD,os.path.join(tmpdir,"CLAUDE.md"))
    subprocess.run(["git","init"],cwd=tmpdir,capture_output=True,check=True)
    subprocess.run(["git","config","user.email","test@edot-autopilot"],cwd=tmpdir,capture_output=True)
    subprocess.run(["git","config","user.name","EDOT Autopilot Eval"],cwd=tmpdir,capture_output=True)
    subprocess.run(["git","add","."],cwd=tmpdir,capture_output=True,check=True)
    subprocess.run(["git","commit","-m","initial: blank FastAPI app, no observability"],cwd=tmpdir,capture_output=True,check=True)
    result=subprocess.run([claude_bin,"--dangerously-skip-permissions","-p",
        f"Observe this project.\nMy Elastic endpoint: {ENDPOINT}\nMy Elastic API key: {API_KEY}",
        "--model","claude-sonnet-4-6","--max-budget-usd","2.00"],cwd=tmpdir,capture_output=True,text=True,timeout=600)
    check("Agent exited cleanly",result.returncode==0,result.stderr[-300:] if result.stderr else "")
    req=open(os.path.join(tmpdir,"requirements.txt")).read() if os.path.exists(os.path.join(tmpdir,"requirements.txt")) else ""
    all_content=req
    for root,_,files in os.walk(tmpdir):
        for f in files:
            if f.endswith('.py') and '.git' not in root: all_content+=open(os.path.join(root,f)).read()
    check("OTel package added to requirements.txt","opentelemetry" in req.lower(),req[:300])
    check("OTel SDK initialized","opentelemetry" in all_content.lower() or "TracerProvider" in all_content,"no OTel init")
    check("OTLP exporter configured","otlp" in all_content.lower(),"no OTLP exporter")
    check("Elastic endpoint configured","ELASTIC_OTLP_ENDPOINT" in all_content or "OTLP_ENDPOINT" in all_content or ENDPOINT.split("//")[-1][:20] in all_content,"endpoint not found")
    env=os.environ.copy(); env.update({"ELASTIC_OTLP_ENDPOINT":ENDPOINT,"ELASTIC_API_KEY":API_KEY,"PORT":str(PORT)})
    pip=subprocess.run(["pip","install","-q","-r","requirements.txt"],cwd=tmpdir,capture_output=True,text=True,timeout=120)
    check("pip install",pip.returncode==0,pip.stderr[-200:] if pip.returncode!=0 else "")
    if pip.returncode==0:
        proc=subprocess.Popen(["python3","main.py"],cwd=tmpdir,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        alive=False
        for _ in range(15):
            time.sleep(1)
            try: urllib.request.urlopen(f"http://localhost:{PORT}/health",timeout=2); alive=True; break
            except: pass
        check("App starts and /health responds",alive,"app did not start in 15s")
        if alive:
            import json,urllib.request as ur
            body=json.dumps({"customer_id":"c1","items":[{"product_id":"p1","qty":1,"price_usd":99.0}]}).encode()
            req_obj=ur.Request(f"http://localhost:{PORT}/orders",data=body,headers={"Content-Type":"application/json"},method="POST")
            try:
                resp=ur.urlopen(req_obj,timeout=5); data=json.loads(resp.read())
                check("POST /orders returns 201",resp.status==201,str(data))
            except Exception as e: check("POST /orders returns 201",False,str(e))
    else:
        check("App starts and /health responds",False,"pip install failed")
        check("POST /orders returns 201",False,"app did not start")
    check(".otel/slos.json created",os.path.exists(os.path.join(tmpdir,".otel","slos.json")))
    check(".otel/golden-paths.md created",os.path.exists(os.path.join(tmpdir,".otel","golden-paths.md")))
finally:
    if proc:
        try: proc.terminate(); proc.wait(timeout=5)
        except: proc.kill()
    if [n for s,n,_ in CHECKS if s=="FAIL"]: print(f"\n  NOTE: Workspace preserved: {tmpdir}")
    else: shutil.rmtree(tmpdir,ignore_errors=True)
passed=sum(1 for s,_,_ in CHECKS if s=="PASS"); failed=sum(1 for s,_,_ in CHECKS if s=="FAIL")
print(f"\n{'='*62}")
for status,name,detail in CHECKS: print(f"  [{status}] {name}"+(f"\n         -> {detail}" if detail and status=="FAIL" else ""))
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed: sys.exit(1)
