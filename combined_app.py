"""
AI 内部提效工具集 — Flask 后端
功能：音频转写+纪要生成+决策追踪 / PDF说明书瘦身 / 智能客服回复
"""
from flask import Flask, render_template, request, jsonify
import openai, json, os, re
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
BASE_URL = "https://api.deepseek.com"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MEETINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meetings.json")

_whisper_model = None
def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model("tiny")
    return _whisper_model

def load_meetings():
    if os.path.exists(MEETINGS_FILE):
        with open(MEETINGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return []

def save_meeting(data):
    meetings = load_meetings()
    data["id"] = len(meetings) + 1
    data["saved_at"] = datetime.now().isoformat()
    meetings.append(data)
    with open(MEETINGS_FILE, "w", encoding="utf-8") as f: json.dump(meetings, f, ensure_ascii=False, indent=2)
    return data

def call_ai(system, user, temp=0.1, max_tok=3000):
    client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        temperature=temp, max_tokens=max_tok)
    return resp.choices[0].message.content

def safe_json(raw):
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].strip().endswith("```"): lines = lines[:-1]
            raw = "\n".join(lines)
        return json.loads(raw)
    except: return []

@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify({"configured": bool(API_KEY and not API_KEY.startswith("sk-your"))})

# ── 会议 ────────────────────────────────────────────────────────
@app.route("/api/meetings", methods=["GET"])
def list_meetings(): return jsonify({"meetings": load_meetings()})

@app.route("/api/meeting/upload-audio", methods=["POST"])
def upload_audio():
    if "audio" not in request.files: return jsonify({"error":"请选择文件"}), 400
    file = request.files["audio"]
    if not file.filename: return jsonify({"error":"文件名为空"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp3",".wav",".m4a",".ogg",".flac",".webm"): return jsonify({"error":f"不支持的格式{ext}"}), 400
    try:
        import tempfile, librosa
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name); tmp_path = tmp.name
        try:
            audio, sr = librosa.load(tmp_path, sr=16000, mono=True)
            transcript = get_whisper().transcribe(audio, language="zh", fp16=False)["text"].strip()
        finally:
            try: os.unlink(tmp_path)
            except: pass
        if not transcript: return jsonify({"error":"转写为空"}), 400
        minutes = call_ai("整理转写稿为结构化纪要。",
            f"整理为：摘要/讨论要点/决策表格/待办表格/关键信息。\n\n{transcript[:6000]}", temp=0.1, max_tok=2000)
        decisions = safe_json(call_ai("只输出JSON数组。",
            f"提取决策(content/owner/deadline)：\n{minutes}", temp=0.0, max_tok=800))
        meeting = save_meeting({"filename":file.filename,"transcript":transcript,"minutes":minutes,"decisions":decisions})
        return jsonify({"success":True,"meeting":meeting})
    except Exception as e: return jsonify({"error":f"转写失败：{str(e)}"}), 500

@app.route("/api/track", methods=["POST"])
def track_decisions():
    data = request.json
    pre_decisions = None
    mid1, mid2 = data.get("meeting1_id"), data.get("meeting2_id")
    if mid1 and mid2:
        meetings = load_meetings()
        m1 = next((m for m in meetings if str(m["id"])==str(mid1)), None)
        m2 = next((m for m in meetings if str(m["id"])==str(mid2)), None)
        if not m1 or not m2: return jsonify({"error":"会议记录不存在"}), 400
        meeting1 = m1.get("minutes") or m1.get("text") or ""
        meeting2 = m2.get("minutes") or m2.get("text") or ""
        if isinstance(m1.get("decisions"), list) and m1["decisions"]: pre_decisions = m1["decisions"]
    else:
        meeting1 = data.get("meeting1","").strip()
        meeting2 = data.get("meeting2","").strip()
    if not meeting1 or not meeting2: return jsonify({"error":"请选择两次会议"}), 400
    try:
        decisions = pre_decisions if pre_decisions else safe_json(call_ai("只输出JSON数组。",
            f"提取决策(content/owner/deadline)：\n{meeting1}", temp=0.0, max_tok=2000))
        tracking = safe_json(call_ai("只输出JSON数组。",
            f"上次决策：{json.dumps(decisions,ensure_ascii=False)}\n本次会议：{meeting2}\n逐条判断done/in_progress/delayed/no_update，含status/evidence/risk_level/comment。", temp=0.1, max_tok=3000))
        new_decisions = safe_json(call_ai("只输出JSON数组。",
            f"提取新决策(content/owner/deadline)，无则[]：\n{meeting2}", temp=0.0, max_tok=1000))
        return jsonify({"decisions":decisions,"tracking":tracking,"new_decisions":new_decisions,
                        "decision_count":len(decisions),"new_count":len(new_decisions)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# ── PDF说明书瘦身 ────────────────────────────────────────────────
@app.route("/api/slim", methods=["POST"])
def slim_manual():
    try:
        if "file" in request.files:
            file = request.files["file"]
            if not file.filename: return jsonify({"error":"文件名为空"}), 400
            if not file.filename.lower().endswith(".pdf"): return jsonify({"error":"仅支持PDF"}), 400
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                file.save(tmp.name); tmp_path = tmp.name
            try:
                from PyPDF2 import PdfReader
                text = "\n".join((p.extract_text() or "") for p in PdfReader(tmp_path).pages).strip()
            finally:
                try: os.unlink(tmp_path)
                except: pass
        else:
            text = (request.get_json(silent=True) or {}).get("manual_text","").strip()
        if not text: return jsonify({"error":"PDF为空或未粘贴文本"}), 400
        result = call_ai("压缩说明书为速查卡。安全警告不删，参数保留，废话删除。",
            f"压缩：\n\n{text[:12000]}", temp=0.1, max_tok=4000)
        return jsonify({"result":result,"orig_chars":len(text),"result_chars":len(result)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# ── 智能客服回复 ────────────────────────────────────────────────
@app.route("/api/email", methods=["POST"])
def email_reply():
    try:
        text = (request.json or {}).get("email","").strip()
        if not text: return jsonify({"error":"请输入消息"}), 400
        lang = "zh" if len(re.findall(r'[一-鿿]',text))/max(len(text),1)>0.3 else "en"
        category = call_ai("只输出一个英文单词。",
            f"分类：shipping/return/product/assembly/parts/complaint/presale/aftersale/distributor/other\n\n{text}",
            temp=0.0, max_tok=10).strip().lower()
        valid = ["shipping","return","product","assembly","parts","complaint","presale","aftersale","distributor","other"]
        normalized = next((v for v in valid if v in category), "other")
        tpl_zh = {"shipping":"物流查询…感谢等待，提供订单号。国内3-7工作日海外5-10天。","return":"退货…表示理解，问订单号和原因。7天无理由30天质量退换。","product":"故障…道歉，要订单号/照片/时间。排查电池刹车显示屏轮胎。保修车架终身电机电池2年。","assembly":"组装…预装85%约30分钟。视频YouTube图文官网。工具随赠。困难推荐车店。","parts":"补发…道歉，要订单号/照片。补发1-3工作日。运费承担。","complaint":"投诉…诚恳道歉不辩解。专人24h跟进。升级主管。","presale":"售前…欢迎，问需求。推荐车型。说明库存价格运费售后。","aftersale":"售后…确认类型。验证订单号保修。维修200+车店。安全停用升级。","distributor":"分销…感谢关注。问地区渠道销量。代理经销。转商务1-3天。","other":"通用…确认收到。转交24h回复。联系方式。"}
        tpl_en = {"shipping":"Reply in English. Shipping inquiry.","return":"Reply in English. Return.","product":"Reply in English. Defect.","assembly":"Reply in English. Assembly.","parts":"Reply in English. Missing parts.","complaint":"Reply in English. Complaint.","presale":"Reply in English. Pre-sale.","aftersale":"Reply in English. After-sale.","distributor":"Reply in English. Distributor.","other":"Reply in English. General reply."}
        reply = call_ai((tpl_en if lang=="en" else tpl_zh).get(normalized,""), text, temp=0.3, max_tok=1500)
        cn = {"shipping":"物流查询","return":"退货退款","product":"产品故障","assembly":"组装教程","parts":"配件补发","complaint":"投诉","presale":"售前咨询","aftersale":"售后问题","distributor":"分销合作","other":"其他"}
        return jsonify({"language":lang,"category":normalized,"category_cn":cn.get(normalized,normalized),"reply":reply})
    except Exception as e: return jsonify({"error":str(e)}), 500

# ── 示例数据 ────────────────────────────────────────────────────
@app.route("/api/demo/<demo_type>")
def get_demo(demo_type):
    demos = {
        "meeting": {
            "m1": """产品周会 2024-06-03  参会：张、李、王、陈
1. Ranger S刹车异响：李已和供应商交涉，对方6月10日前提供改进方案。张决定不达标则换供应商。
2. Mars 2.0折叠扣偏紧：要求李联系模具厂开新模，预算5万，6月底完成。
3. 德国TUV认证：德国客户电池无TUV认证被海关扣货。张决定让李联系TUV机构，7月完成。
4. 客服组装说明书英文翻译错误多，张决定外包翻译，预算3000元。
5. 小红书达人：王提议和3个骑行博主合作。张同意，要王本周出达人名单报价。""",
            "m2": """产品周会 2024-06-10  参会：张、李、王、陈
1. Ranger S刹车：供应商已提交方案，换刹车片材质，样品寄出待测试。李预计周五收到。
2. Mars 2.0折叠扣：模具厂反馈需微调设计，李沟通中，略有延迟。张要求7月中完成。
3. 德国TUV：李已联系两家机构，报价差距大，需张决定选哪家。
4. 说明书翻译：翻译公司已交付英文初稿，陈在审核。
5. 小红书达人：王已筛出5个备选，2个报价偏高需砍价。张要求下周定最终名单。
6. 新增-日本准入：张提出日本对电自助力比限制严格，需调研现有车型是否合规。李认领，下周汇报。"""
        },
        "email": {
            "zh_shipping":"你好，我的订单HB20240710，下单10天了还没收到，帮我查一下到哪里了？",
            "zh_product":"上周买的Ranger S，骑了三天刹车就吱吱响，声音很大不敢骑了。",
            "zh_presale":"你好，我想买一辆上下班通勤的电动车，预算3000左右，有什么推荐吗？",
            "en_shipping":"Hi, I ordered a Heybike Mars 2 weeks ago. The tracking shows no update for 5 days. When will it arrive?",
            "en_product":"I just got my new Bravo and the battery won't charge at all. The charger light stays green. Please help!",
            "zh_complaint":"你们客服怎么回事，打了三次电话都没人接，我要投诉！",
            "zh_distributor":"您好，我是杭州的自行车实体经销商，对Heybike的代理合作感兴趣，请问怎么对接？",
        }
    }
    return jsonify(demos.get(demo_type, {}))

if __name__ == "__main__":
    try:
        get_whisper()
    except:
        pass
    app.run(host="0.0.0.0", port=5000, debug=False)
