import base64, json, os, sys, time, urllib.request
HUB = "https://hub-cloud.browserstack.com/wd/hub"
AUTH = "Basic " + base64.b64encode(f"{os.environ['BROWSERSTACK_USERNAME']}:{os.environ['BROWSERSTACK_ACCESS_KEY']}".encode()).decode()
def call(method, path, body=None):
    req = urllib.request.Request(HUB + path, method=method, headers={"Authorization": AUTH, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=300) as r: return json.load(r).get("value")
    except urllib.error.HTTPError as e:
        return {"http": e.code, **(json.load(e).get("value") or {})}
page = open(sys.argv[1]).read()
caps = {"capabilities": {"alwaysMatch": {"browserName": "chrome", "bstack:options": {
    "deviceName": sys.argv[2], "osVersion": sys.argv[3], "realMobile": "true",
    "sessionName": "phone-use probe", "buildName": "phone-use"}}}}
v = call("POST", "/session", caps); sid = v.get("sessionId") if isinstance(v, dict) else None
print("session:", bool(sid), "" if sid else str(v)[:300]); 
if not sid: sys.exit(1)
try:
    s = f"/session/{sid}"
    call("POST", s + "/url", {"url": "data:text/html;base64," + base64.b64encode(page.encode()).decode()}); time.sleep(3)
    print("title before:", call("GET", s + "/title"))
    nf = call("POST", s + "/element", {"using": "css selector", "value": "#NoSuchElement_phoneuse"})
    print("missing element ->", nf.get("http"), nf.get("error"))
    print("contexts:", call("GET", s + "/contexts"))
    call("POST", s + "/context", {"name": "NATIVE_APP"})
    r = call("GET", s + "/window/rect"); w, h = r["width"], r["height"]; cx, cy = w // 2, h // 2
    print("native rect:", w, h)
    def finger(i, x0, y0, x1, y1):
        return {"type": "pointer", "id": f"f{i}", "parameters": {"pointerType": "touch"}, "actions": [
            {"type": "pointerMove", "duration": 0, "x": x0, "y": y0}, {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": 700, "x": x1, "y": y1}, {"type": "pointerUp", "button": 0}]}
    d = int(min(w, h) * 0.05); D = int(min(w, h) * 0.35)
    print("pinch-out:", call("POST", s + "/actions", {"actions": [finger(1, cx - d, cy - d, cx - D, cy - D), finger(2, cx + d, cy + d, cx + D, cy + D)]}))
    time.sleep(2)
    ctxs = call("GET", s + "/contexts"); web = [c for c in ctxs if c != "NATIVE_APP"][0]
    call("POST", s + "/context", {"name": web})
    print("title after:", call("GET", s + "/title"))
finally:
    print("delete:", call("DELETE", f"/session/{sid}"))
