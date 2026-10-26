"""Form inspection shared by preparation and browser execution."""
from html.parser import HTMLParser
import re

AUTH_PATTERN = re.compile(r"sponsor|visa|authori[sz].*work|immigration|\b[CO]PT\b|work.*permit|\bF-?1\b", re.I)
CONFIRMATION = re.compile(r"(?:your\s+)?application\s+(?:(?:has been|was|is)\s+)?(?:successfully\s+)?(?:received|submitted)|thank you for (?:applying|your application)", re.I)


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = ""
        self.method = "post"
        self.fields = []
        self.labels = {}
        self._label = None
        self._select = None
        self._option = None
        self._in_form = False
        self._seen_form = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and not self._seen_form:
            self._seen_form = self._in_form = True
            self.action, self.method = a.get("action", ""), a.get("method", "post").lower()
        if tag == "label":
            self._label = {"for": a.get("for"), "text": "", "fields": []}
        if tag in ("input", "select", "textarea") and self._in_form and a.get("name") and "disabled" not in a:
            f = {"name": a["name"], "id": a.get("id", ""), "type": a.get("type", tag),
                 "required": "required" in a, "label": a.get("aria-label", ""),
                 "value": a.get("value", ""), "options": []}
            self.fields.append(f)
            if self._label:
                self._label["fields"].append(f)
            if tag == "select":
                self._select = f
        if tag == "option" and self._select is not None:
            self._option = {"value": a.get("value"), "label": ""}

    def handle_data(self, data):
        if self._label is not None:
            self._label["text"] += data
        if self._option is not None:
            self._option["label"] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self._in_form = False
        if tag == "option" and self._option is not None:
            self._option["label"] = self._option["label"].strip()
            if self._option["value"] is None:
                self._option["value"] = self._option["label"]
            self._select["options"].append(self._option)
            self._option = None
        if tag == "select":
            self._select = None
        if tag == "label" and self._label is not None:
            label = self._label["text"].strip()
            self.labels[self._label["for"]] = label
            for field in self._label["fields"]:
                field["label"] = label
            self._label = None

    def close(self):
        super().close()
        for field in self.fields:
            field["label"] = field["label"] or self.labels.get(field["id"]) or field["name"]


# This runs inside the inspected page and only reads form controls.
BROWSER_FIELDS = r"""() => {
 const form = [...document.forms].find(f => f.querySelector('input[type=email],input[id=first_name],input[name=first_name],input[type=file]'));
 if (!form) return [];
 const fields = new Map();
 for (const e of form.querySelectorAll('input,select,textarea')) {
   const name = e.name || e.id;
   if (!name || e.disabled) continue;
   const label = e.getAttribute('description') || e.getAttribute('aria-label') || [...(e.labels || [])].map(l=>l.innerText).join(' ').trim() || name;
   const type = e.getAttribute('role')==='combobox' ? 'combobox' : (e.type || e.tagName.toLowerCase());
   const f = {name,id:e.id,type,required:e.required || e.getAttribute('aria-required')==='true',
     label:label.replace(/\s*\*\s*$/, '').trim(),value:e.value,
     options:e.options ? [...e.options].map(o=>({label:o.text,value:o.value})) : [],multiple:!!e.multiple};
   if (type==='checkbox' || type==='radio') {
     f.options=[{label:[...(e.labels||[])].map(l=>l.innerText).join(' ').trim() || e.value,value:e.value || 'on'}];
     f.multiple=type==='checkbox';
     if (fields.has(name)) { fields.get(name).options.push(...f.options); continue; }
   }
   fields.set(name,f);
 }
 return [...fields.values()];
}"""
