# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Arabic for the Live voice agent and the Home chat's own lines, keyed by the
exact English text: the call panel's words (components/live_agent), the
offline agent's tool errors (services/live_agent.py) and the chat's steps
(services/studio_chat.py)."""

# English text -> Arabic.
AR_TEXT: dict[str, str] = {
    # Call panel (components/live_agent/live_agent.py _STRING_KEYS)
    "Talk to the studio": "تحدّث مع الاستوديو",
    "Ask for images and videos by voice. Jobs run side by side.": (
        "اطلب الصور والفيديو بصوتك. تعمل المهام جنباً إلى جنب."
    ),
    "Connecting…": "جارٍ الاتصال…",
    "Listening": "أستمع",
    "Speaking": "أتحدث",
    "Offline mode (typed)": "وضع دون اتصال (بالكتابة)",
    "Type a request…": "اكتب طلبك…",
    "Mute microphone": "كتم الميكروفون",
    "Unmute microphone": "تشغيل الميكروفون",
    "End call": "إنهاء المكالمة",
    "Jobs": "المهام",
    "Download": "تنزيل",
    "Close": "إغلاق",
    "No microphone access. You can still type.": (
        "لا يمكن الوصول إلى الميكروفون. ما زال بإمكانك الكتابة."
    ),
    "Minimize": "تصغير",
    "Expand": "تكبير",
    "Restore": "استعادة",
    "Type instead": "اكتب بدلاً من ذلك",
    "Things you ask for show up here.": "ما تطلبه يظهر هنا.",
    "Turn the avatar off": "أوقف الصورة الرمزية",
    "Turn the avatar on": "شغّل الصورة الرمزية",
    "Avatar": "الصورة الرمزية",
    "Show a talking presenter instead of voice only. Uses much more of the Live quota.": (
        "اعرض مقدّماً يتحدث بدل الصوت فقط. يستهلك حصة أكبر بكثير من Live."
    ),
    "This browser cannot play the avatar, so the call is voice only.": (
        "هذا المتصفح لا يشغّل الصورة الرمزية، لذا المكالمة صوتية فقط."
    ),
    "Reading the page": "أقرأ الصفحة",
    "Filling the page": "أملأ الصفحة",
    "Opening the page": "أفتح الصفحة",
    "Watching the film": "أشاهد الفيلم",
    "Starting the fix": "أبدأ الإصلاح",
    "Sign in again to use the voice agent.": "سجّل الدخول مرة أخرى لاستخدام المساعد الصوتي.",
    "The voice agent is turned off on this server.": "المساعد الصوتي متوقف على هذا الخادم.",
    "Failed": "فشل",
    # Tool errors and notes the offline agent says (services/live_agent.py)
    "There is no image yet. Make one first.": "لا توجد صورة بعد. اصنع واحدة أولاً.",
    "That image is not ready yet, so I can't animate it.": (
        "هذه الصورة ليست جاهزة بعد، لذا لا أستطيع تحريكها."
    ),
    "There is no story yet. Create one first.": "لا توجد قصة بعد. أنشئ واحدة أولاً.",
    "There is no story yet.": "لا توجد قصة بعد.",
    "This film is not rendered yet, so there is nothing to fix.": (
        "لم يُخرَج هذا الفيلم بعد، فلا يوجد ما يُصلَح."
    ),
    "There are no jobs yet.": "لا توجد مهام بعد.",
    "There is nothing to download yet.": "لا يوجد ما يُنزَّل بعد.",
    "The story is gone.": "القصة لم تعد موجودة.",
    "The screen did not answer in time.": "لم تستجب الشاشة في الوقت المناسب.",
    "The film is already rendered.": "الفيلم مُخرَج بالفعل.",
    "Scenario approved. Call continue_story again to build the set.": (
        "تمت الموافقة على السيناريو. اطلب الخطوة التالية لبناء الديكور."
    ),
    "Write the scenario first before rendering the film.": "اكتب السيناريو أولاً قبل إخراج الفيلم.",
    "Approve the scenario first before rendering the film.": (
        "وافق على السيناريو أولاً قبل إخراج الفيلم."
    ),
    "Every scene needs a storyboard frame first.": "كل مشهد يحتاج إطاراً من لوحة القصة أولاً.",
    "Describe your idea in a sentence or two first.": "صف فكرتك في جملة أو جملتين أولاً.",
    "The model is busy right now. Try again in a moment.": (
        "النموذج مشغول الآن. حاول مرة أخرى بعد لحظة."
    ),
    "The model declined this prompt. Try different wording.": (
        "رفض النموذج هذا الوصف. جرّب صياغة مختلفة."
    ),
    "This took too long. Try again.": "استغرق ذلك وقتاً طويلاً. حاول مرة أخرى.",
    "The model service had an error. Try again.": "حدث خطأ في خدمة النموذج. حاول مرة أخرى.",
    # Home chat steps (services/studio_chat.py)
    "Reading your message": "أقرأ رسالتك",
    "Offline helper": "المساعد دون اتصال",
    "Found settings in your message": "وجدت إعدادات في رسالتك",
    "Could not reach Gemini": "تعذّر الوصول إلى Gemini",
    "Wrote the reply": "كتبت الرد",
    "Could not do that": "تعذّر ذلك",
    "Checked your jobs": "راجعت مهامك",
    "Checked the film": "راجعت الفيلم",
    "Planned the fix": "خطّطت للإصلاح",
    "Moved the film on": "نقلت الفيلم إلى الخطوة التالية",
}

# (regex on the English text, Arabic template with {0}, {1}...) for text built at runtime.
PATTERNS: list[tuple[str, str]] = [
    (r"^(.+) is not finished yet\.$", "لم تنتهِ {0} بعد."),
    (
        r"^(.+) is still (?:queued|running)\. Edit it once it is ready\.$",
        "{0} ما زالت قيد العمل. عدّلها عندما تجهز.",
    ),
    (r"^Could not plan the fix: (.+)$", "تعذّر التخطيط للإصلاح: {0}"),
    (
        r"^(\d+) jobs are already running\. Wait for one to finish\.$",
        "{0} مهام قيد التشغيل بالفعل. انتظر حتى تنتهي إحداها.",
    ),
    (r"^Used (.+)$", "استخدمت {0}"),
]
