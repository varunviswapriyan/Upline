import base64
import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from xml.sax.saxutils import escape


def _env(*names, default=""):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    return default


class Notifier:
    def __init__(self):
        self.tw_sid = _env("UPLINE_TWILIO_SID", "TWILIO_ACCOUNT_SID")
        self.tw_token = _env("UPLINE_TWILIO_TOKEN", "TWILIO_AUTH_TOKEN")
        self.tw_from = _env("UPLINE_TWILIO_FROM", "TWILIO_FROM_NUMBER")
        self.tw_base = _env("UPLINE_TWILIO_BASE", default="https://api.twilio.com")
        self.smtp_user = _env("UPLINE_SMTP_USER")
        self.smtp_pass = _env("UPLINE_SMTP_PASS")
        self.smtp_host = _env("UPLINE_SMTP_HOST", default="smtp.gmail.com")
        self.smtp_port = int(_env("UPLINE_SMTP_PORT", default="465"))
    # reports status of configuration of communication channels
    def status(self):
        tw = bool(self.tw_sid and self.tw_token and self.tw_from)
        return {"sms": tw, "voice": tw, "email": bool(self.smtp_user and self.smtp_pass), "push": True}
    # cleans phone number
    @staticmethod
    def phone(raw):
        d = re.sub(r"[^\d+]", "", raw or "")
        if d.startswith("+") and 10 <= len(d) <= 16:
            return d
        d = d.lstrip("+")
        if len(d) == 10:
            return "+1" + d
        if len(d) == 11 and d.startswith("1"):
            return "+" + d
        return None
    # checks email format
    @staticmethod
    def email(raw):
        raw = (raw or "").strip()
        return raw if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw) else None
    # hides contact details
    @staticmethod
    def mask(to):
        if "@" in to:
            name, dom = to.split("@", 1)
            return name[:1] + "•••@" + dom
        return "•••" + to[-4:]
    # makes POST request to Twilio for SMS and voice
    def _twilio(self, path, data):
        url = f"{self.tw_base}/2010-04-01/Accounts/{self.tw_sid}/{path}"
        auth = base64.b64encode(f"{self.tw_sid}:{self.tw_token}".encode()).decode()
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                     headers={"Authorization": f"Basic {auth}", "User-Agent": "Upline/1.0",
                                              "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ctx()) as r:
                out = json.loads(r.read())
            return {"ok": True, "id": out.get("sid")}
        except urllib.error.HTTPError as ex:
            try:
                msg = json.loads(ex.read()).get("message", "")
            except Exception:
                msg = ""
            hint = " (Twilio trial accounts can only reach numbers you've verified in the Twilio console)" \
                if ex.code in (400, 403) else ""
            return {"ok": False, "error": f"Twilio error {ex.code}: {msg}{hint}"}
        except Exception as ex:
            return {"ok": False, "error": f"Couldn't reach Twilio: {ex}"}
    # chooses delivery method, validates recipient, sends messages
    def send(self, channel, to, items):
        st = self.status()
        if channel in ("sms", "voice", "email") and not st[channel]:
            return {"ok": False, "error": "not_configured"}
        # HTTP using Twilio
        if channel in ("sms", "voice"):
            num = self.phone(to)
            if not num:
                return {"ok": False, "error": "Please enter a valid phone number."}
            if channel == "sms":
                res = [self._twilio("Messages.json", {"To": num, "From": self.tw_from, "Body": it["text"][:1500]})
                       for it in items]
            else:
                spoken = " ".join(f"<Say voice=\"Polly.Joanna\">{escape(it['title'])}. {escape(_speakable(it['text']))}</Say>"
                                  "<Pause length=\"1\"/>" for it in items)
                twiml = f"<Response><Pause length=\"1\"/>{spoken}<Say>Goodbye.</Say></Response>"
                res = [self._twilio("Calls.json", {"To": num, "From": self.tw_from, "Twiml": twiml})]
            ok = all(r["ok"] for r in res)
            return {"ok": ok, "to": self.mask(num), "results": res,
                    "error": next((r["error"] for r in res if not r["ok"]), None)}
        # SMTP
        if channel == "email":
            addr = self.email(to)
            if not addr:
                return {"ok": False, "error": "Please enter a valid email address."}
            try:
                ctx = _ctx()
                if self.smtp_port == 465:
                    s = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx, timeout=20)
                else:
                    s = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20)
                    s.ehlo()
                    if s.has_extn("starttls"):
                        s.starttls(context=ctx)
                        s.ehlo()
                with s:
                    s.login(self.smtp_user, self.smtp_pass)
                    for it in items:
                        m = EmailMessage()
                        m["Subject"] = f"Upline: {it['title']}"
                        m["From"] = f"Upline outage alerts <{self.smtp_user}>"
                        m["To"] = addr
                        body = it["text"].replace("Upline: ", "", 1)
                        m.set_content(body + "\n\nEstimates are not utility commitments. See a downed wire? "
                                             "Stay 30 feet away and call 911.")
                        m.add_alternative(_email_html(it["title"], body), subtype="html")
                        s.send_message(m)
                return {"ok": True, "to": self.mask(addr)}
            except smtplib.SMTPAuthenticationError:
                return {"ok": False, "error": "Email login failed. For Gmail, use an App Password, not your normal password."}
            except Exception as ex:
                return {"ok": False, "error": f"Couldn't send email: {ex}"}
        return {"ok": False, "error": "unknown channel"}

# creates SSL context for secure connections
def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

# make notification text easier to read by tts
def _speakable(t):
    t = t.replace("Upline: ", "", 1).replace("~", "about ").replace("½", " and a half")
    return re.sub(r"(\d+)%", r"\1 percent", t)

# generates html of email
def _email_html(title, body):
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;border:1px solid #D6DFDD;border-radius:14px;overflow:hidden">
  <div style="background:#102A33;color:#fff;padding:16px 20px;font-size:20px;font-weight:bold">⚡ Upline <span style="color:#F2B33D">·</span> outage alert</div>
  <div style="padding:18px 20px;color:#102A33">
    <div style="font-size:18px;font-weight:bold;margin-bottom:8px">{escape(title)}</div>
    <div style="font-size:15px;line-height:1.5">{escape(body)}</div>
    <div style="margin-top:16px;padding:10px 12px;background:#FBEDEA;border-radius:10px;font-size:13px">⚠️ See a downed wire? Stay 30 feet away and call 911.</div>
    <div style="margin-top:14px;font-size:12px;color:#75878C">Upline storm alerts · Estimates are not utility commitments.</div>
  </div></div>"""
