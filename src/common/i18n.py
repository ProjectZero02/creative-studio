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
"""English / Arabic text for the shared chrome.

Three ways to get text:

* ``t("key")`` reads the language from ``AppState.lang``. English is the
  fallback for any key Arabic lacks, so a missing translation never breaks.
* ``tr("key", english)`` returns ``english`` in English and the Arabic entry
  (if any) in Arabic. Use it where a page passes its own English copy, such as
  the header's one-line purpose.
* ``tx(english)`` translates a string a page passed to a shared component
  (stage names, empty states, placeholders) by its exact English text, with a
  few patterns for strings that embed a model name ("Sending to Veo").

Product and model names stay in Latin script in Arabic (Nano Banana, Gemini
Omni, Veo, Lyria, Chirp, Vertex AI, Google Cloud).
"""

from __future__ import annotations

import re

LANGS = ("en", "ar")
DEFAULT_LANG = "en"
RTL_LANGS = frozenset({"ar"})
LANG_COOKIE = "gm_lang"


# --------------------------------------------------------------------------- #
# Keyed strings                                                               #
# --------------------------------------------------------------------------- #
EN: dict[str, str] = {
    # Language switch
    "lang.name.en": "English",
    "lang.name.ar": "العربية",
    "lang.label": "Language",
    "lang.switch": "Switch to Arabic (العربية)",
    # Brand / side nav
    "brand.sub": "on Vertex AI",
    "nav.open_menu": "Open menu",
    "nav.close_menu": "Close menu",
    "nav.to_light": "Switch to light mode",
    "nav.to_dark": "Switch to dark mode",
    "nav.light_mode": "Light mode",
    "nav.dark_mode": "Dark mode",
    "nav.group.foundation": "Create",
    "nav.group.workflows": "Industry demos",
    "nav.group.studio": "Your work",
    # Nav items, keyed by route (leading slash dropped, "-" -> "_")
    "nav.home": "Home",
    "nav.home.desc": "The home page of the application.",
    "nav.nano_banana": "Image Studio",
    "nav.nano_banana.desc": "Create and edit images with Nano Banana.",
    "nav.veo": "Video Studio",
    "nav.veo.desc": "Make video from a prompt, a picture or two frames.",
    "nav.story": "Story Studio",
    "nav.story.desc": "One idea to a finished film, with music and voice.",
    "nav.voice": "Voice",
    "nav.voice.desc": "Natural speech in 130+ languages with Gemini TTS.",
    "nav.lyria": "Music",
    "nav.lyria.desc": "Original music, with or without lyrics.",
    "nav.fashion": "Fashion",
    "nav.fashion.desc": "Dress a model in any outfit, or build a shop-the-look set.",
    "nav.object_rotation": "Product 360",
    "nav.object_rotation.desc": "Turn one product photo into a 360° turntable video.",
    "nav.interior_design": "Interiors",
    "nav.interior_design.desc": "A floor plan to furnished rooms and a walkthrough.",
    "nav.starter_pack": "Brand kit",
    "nav.starter_pack.desc": "A set of on-brand images from one campaign idea.",
    "nav.library_v2": "Library",
    "nav.library_v2.desc": "Browse your generated media.",
    "nav.gemini_omni": "Gemini Omni",
    "nav.gemini_omni.desc": "Generate and edit videos from text, images, or base video inputs using Gemini Omni.",
    "nav.gemini_tts": "Gemini TTS",
    "nav.gemini_tts.desc": "Gemini's latest Text to Speech mode",
    "nav.gemini_writers_workshop": "Gemini",
    "nav.gemini_writers_workshop.desc": "Collaborate with Gemini in the Writers Workshop",
    "nav.chirp_3hd": "Chirp 3 HD",
    "nav.chirp_3hd.desc": "Generate high-definition speech from text using Chirp 3.",
    "nav.vto": "Virtual Try-On",
    "nav.vto.desc": "Virtually try on clothing items.",
    "nav.motion_portraits": "Motion Portraits",
    "nav.motion_portraits.desc": "Create animated portraits from a still image.",
    "nav.character_consistency": "Character Consistency",
    "nav.character_consistency.desc": "Create consistent characters across multiple images and videos.",
    "nav.shop_the_look": "Shop the Look",
    "nav.shop_the_look.desc": "Create a 'shop the look' experience from a model and clothing.",
    "nav.storyboarder": "Storyboarder",
    "nav.storyboarder.desc": "Create multi-scene narrative video storyboards.",
    "nav.pixie_compositor": "Pixie Compositor",
    "nav.pixie_compositor.desc": "Pixie helps you combine generative media.",
    "nav.labs": "Labs",
    "nav.labs.desc": "Odd things are bubbling.",
    "nav.about": "About",
    "nav.about.desc": "Information about GenMedia Creative Studio.",
    "nav.config": "Settings",
    "nav.config.desc": "Configure application settings.",
    "nav.admin_users": "Users",
    # Page header purposes (the line each page passes to header())
    "page.nano_banana.purpose": "Create and edit images from a prompt and your own pictures with Gemini.",
    "page.veo.purpose": "Make, edit, extend or upscale video clips with Gemini Omni or Veo.",
    "page.voice.purpose": "Turn a script into natural speech in 130+ languages.",
    "page.lyria.purpose": "Compose music and songs from a description, with optional lyrics.",
    "page.fashion.purpose": "Dress a model in any piece of clothing, or style a whole look from a catalog.",
    "page.object_rotation.purpose": "Turn one product photo into four studio views and a 360° spin video.",
    "page.interior_design.purpose": "Turn a floor plan into a 3D view, restyle each room and make a video tour.",
    "page.starter_pack.purpose": "Generate a set of on-brand images for a product or campaign from one idea.",
    "page.admin_users.purpose": "Add people, set their role and reset passwords. Only admins see this page.",
    "header.about": "About this page",
    # Avatar menu
    "menu.account": "Account",
    "menu.account_of": "Account: {name}",
    "menu.admin": "Admin",
    "menu.user": "User",
    "menu.dark_mode": "Dark mode",
    "menu.users": "Users",
    "menu.settings": "Settings",
    "menu.account_settings": "Account settings",
    "menu.about": "About",
    "menu.sign_out": "Sign out",
    "menu.guest": "Guest",
    "menu.not_signed_in": "Not signed in",
    # Composer
    "composer.placeholder": "Describe what you want to create…",
    "composer.enhance": "Enhance prompt",
    "composer.send": "Generate",
    "composer.hint": "Enter to generate · Shift+Enter for a new line",
    "composer.hint_short": "Enter to generate",
    "composer.clear": "Clear prompt and results",
    "composer.generating": "Generating",
    "composer.remove": "Remove {label}",
    # Results
    "results.recent": "Recent",
    "results.latest": "Latest",
    "results.count_one": "{n} item this session",
    "results.count_other": "{n} items this session",
    "card.download": "Download",
    "card.open": "Open larger",
    "card.reuse": "Reuse prompt",
    "card.video": "Make a video from this image",
    "card.extend": "Extend this video",
    "card.edit": "Edit this image",
    "card.edit_video": "Edit this video",
    "card.upscale": "Upscale this video",
    "card.actions": "Actions",
    "card.play": "Play: {name}",
    "card.open_item": "Open: {name}",
    "card.generated": "Generated item",
    # Progress card
    "progress.creating": "Creating your {media}",
    "progress.failed": "Couldn't create your {media}",
    "progress.done": "Done",
    "progress.kept": "Your prompt and settings are kept.",
    "progress.usually": "usually ~{t}",
    "progress.generic_error": "Something went wrong on our side.",
    "progress.retry": "Try again",
    "progress.dismiss": "Dismiss",
    "progress.st_done": "(done)",
    "progress.st_now": "(in progress)",
    "progress.st_failed": "(failed)",
    "progress.aria": "Generation progress",
    "progress.elapsed": "Elapsed time",
    "progress.estimated": "Estimated progress",
    "media.image": "image",
    "media.video": "video",
    "media.audio": "audio",
    "media.music": "music",
    # Errors (components/generation_progress.friendly_error)
    "error.unknown": "Unknown error.",
    "error.credentials": (
        "The studio couldn't sign in to Google Cloud. "
        "Check the service account or run `gcloud auth application-default login`."
    ),
    "error.quota": "The model is busy (quota reached). Wait a minute and try again.",
    "error.safety": "The request was blocked by safety filters. Try rewording the prompt.",
    "dialog.close": "Close",
    "dialog.error_title": "Generation Error",
    # Sign-in page (/login)
    "login.title": "Sign in | GenMedia Studio",
    "login.visual_title": "Create with Google's generative media models.",
    "login.visual_body": "Image, video, music and speech on Vertex AI, in one studio.",
    "login.visual_foot": "Your work stays in your own Google Cloud project.",
    "login.tile_image": "Image",
    "login.tile_image_sub": "Gemini Image and Imagen",
    "login.tile_video": "Video",
    "login.tile_music": "Music",
    "login.tile_speech": "Speech",
    "login.tile_speech_sub": "Gemini TTS and Chirp 3 HD",
    "login.welcome": "Welcome back",
    "login.lead": "Sign in to GenMedia Studio.",
    "login.email": "Email",
    "login.password": "Password",
    "login.show": "Show",
    "login.hide": "Hide",
    "login.sr_password": " password",
    "login.submit": "Sign in",
    "login.help": "No account yet? Ask your studio admin to add you.",
    "login.err_expired": "This page expired. Please sign in again.",
    "login.err_too_many": "Too many tries. Wait 5 minutes, then try again.",
    "login.err_generic": "Email or password is wrong.",
    # /account (signed-in user's own settings)
    "account.title": "Account settings",
    "account.lead": "Signed in as {email}.",
    "account.password_heading": "Change password",
    "account.current": "Current password",
    "account.new": "New password",
    "account.confirm": "Confirm new password",
    "account.rule": "At least {n} characters.",
    "account.submit": "Change password",
    "account.back": "Back to the studio",
    "account.changed": "Password changed. Other devices have been signed out.",
    "account.err_expired": "This page expired. Please try again.",
    "account.err_current": "Your current password is wrong.",
    "account.err_mismatch": "The new passwords do not match.",
    "account.err_short": "Use at least {n} characters.",
    "account.err_long": "Use at most 256 characters.",
    "account.err_same": "Choose a password different from your current one.",
    "account.err_too_many": "Too many tries. Wait 5 minutes, then try again.",
    # /admin/users
    "admin.col_name": "Name",
    "admin.col_email": "Email",
    "admin.col_role": "Role",
    "admin.col_status": "Status",
    "admin.col_created": "Created",
    "admin.col_last": "Last sign-in",
    "admin.col_actions": "Actions",
    "admin.role_admin": "Admin",
    "admin.role_user": "User",
    "admin.active": "Active",
    "admin.disabled": "Disabled",
    "admin.never": "Never",
    "admin.you": " (you)",
    "admin.reset_password": "Reset password",
    "admin.disable": "Disable",
    "admin.enable": "Enable",
    "admin.dismiss": "Dismiss",
    "admin.add_user": "Add user",
    "admin.add_help": "They sign in with this email and the temporary password.",
    "admin.name": "Name",
    "admin.email": "Email",
    "admin.role": "Role",
    "admin.role_user_long": "User: can use the studio",
    "admin.role_admin_long": "Admin: can also manage users",
    "admin.temp_password": "Temporary password",
    "admin.new": "New",
    "admin.cancel": "Cancel",
    "admin.reset_help": "Set a new password for {email}. Their current sessions end.",
    "admin.new_password": "New password",
    "admin.search": "Search by name or email",
    "admin.no_match": "No users match.",
    "admin.no_users": "No users yet.",
    "admin.count_one": "{n} user",
    "admin.count_other": "{n} users",
    "admin.only_admins": "Only admins can manage users.",
    # Home page
    "home.eyebrow": "Google Cloud · Vertex AI",
    "home.title": "Google's creative AI, in one studio",
    "home.lede": "Turn one idea into images, video, voice and music, or a finished short film.",
    "home.create": "Create",
    "home.create_sub": "Google's latest models for images, video, film, voice and music.",
    "home.demos": "Industry demos",
    "home.demos_sub": "Ready-made flows for retail, products, real estate and marketing.",
    "home.badge.new": "New",
    "home.badge.story": "Idea to film",
    "home.prompt.what": "What to make",
    "home.prompt.describe": "Describe your idea",
    "home.prompt.try": "Try:",
    "home.mode.image.label": "Image",
    "home.mode.image.action": "Create image",
    "home.mode.image.placeholder": "Describe an image to create or edit",
    "home.mode.image.ex1": "A perfume bottle on wet black stone, studio light",
    "home.mode.image.ex2": "Our sneaker on a Tokyo street at night",
    "home.mode.video.label": "Video",
    "home.mode.video.action": "Create video",
    "home.mode.video.placeholder": "Describe a shot: subject, action, camera",
    "home.mode.video.ex1": "Slow dolly in on a barista pouring latte art",
    "home.mode.video.ex2": "Drone shot over a desert road at sunrise",
    "home.mode.film.label": "Film",
    "home.mode.film.action": "Create film",
    "home.mode.film.placeholder": "One idea for a short film, with music and voice",
    "home.mode.film.ex1": "A 30-second ad for an electric bike in the city",
    "home.mode.film.ex2": "A lighthouse keeper finds a message in a bottle",
    "home.mode.voice.label": "Voice",
    "home.mode.voice.action": "Create voice",
    "home.mode.voice.placeholder": "Type a script to turn into natural speech",
    "home.mode.voice.ex1": "Welcome to our store. Today only, everything is 20% off.",
    "home.mode.voice.ex2": "Thanks for calling. Your order is on its way.",
    "home.mode.music.label": "Music",
    "home.mode.music.action": "Create music",
    "home.mode.music.placeholder": "Describe a track: mood, instruments, tempo",
    "home.mode.music.ex1": "Warm lo-fi beat with soft piano, 80 bpm",
    "home.mode.music.ex2": "Uplifting cinematic strings for a product launch",
}

AR: dict[str, str] = {
    "lang.name.en": "English",
    "lang.name.ar": "العربية",
    "lang.label": "اللغة",
    "lang.switch": "التبديل إلى الإنجليزية (English)",
    "brand.sub": "على Vertex AI",
    "nav.open_menu": "فتح القائمة",
    "nav.close_menu": "إغلاق القائمة",
    "nav.to_light": "التبديل إلى الوضع الفاتح",
    "nav.to_dark": "التبديل إلى الوضع الداكن",
    "nav.light_mode": "الوضع الفاتح",
    "nav.dark_mode": "الوضع الداكن",
    "nav.group.foundation": "إنشاء",
    "nav.group.workflows": "عروض القطاعات",
    "nav.group.studio": "أعمالك",
    "nav.home": "الرئيسية",
    "nav.home.desc": "الصفحة الرئيسية للتطبيق.",
    "nav.nano_banana": "استوديو الصور",
    "nav.nano_banana.desc": "أنشئ الصور وعدّلها باستخدام Nano Banana.",
    "nav.veo": "استوديو الفيديو",
    "nav.veo.desc": "أنشئ فيديو من وصف نصي أو صورة أو إطارين.",
    "nav.story": "استوديو القصص",
    "nav.story.desc": "من فكرة واحدة إلى فيلم مكتمل بالموسيقى والتعليق الصوتي.",
    "nav.voice": "الصوت",
    "nav.voice.desc": "كلام طبيعي بأكثر من 130 لغة باستخدام Gemini TTS.",
    "nav.lyria": "الموسيقى",
    "nav.lyria.desc": "موسيقى أصلية، مع كلمات أو بدونها.",
    "nav.fashion": "الأزياء",
    "nav.fashion.desc": "ألبِس العارضة أي زيّ، أو أنشئ مجموعة «تسوّق الإطلالة».",
    "nav.object_rotation": "المنتج 360°",
    "nav.object_rotation.desc": "حوّل صورة منتج واحدة إلى فيديو دوّار بزاوية 360°.",
    "nav.interior_design": "التصميم الداخلي",
    "nav.interior_design.desc": "من مخطط الطابق إلى غرف مفروشة وجولة مصوّرة.",
    "nav.starter_pack": "حزمة العلامة",
    "nav.starter_pack.desc": "مجموعة صور تناسب علامتك التجارية من فكرة حملة واحدة.",
    "nav.library_v2": "المكتبة",
    "nav.library_v2.desc": "تصفّح الوسائط التي أنشأتها.",
    "nav.gemini_omni": "Gemini Omni",
    "nav.gemini_omni.desc": "أنشئ مقاطع الفيديو وعدّلها من نص أو صور أو فيديو أساسي باستخدام Gemini Omni.",
    "nav.gemini_tts": "Gemini TTS",
    "nav.gemini_tts.desc": "أحدث وضع لتحويل النص إلى كلام من Gemini.",
    "nav.gemini_writers_workshop": "Gemini",
    "nav.gemini_writers_workshop.desc": "تعاون مع Gemini في ورشة الكتابة.",
    "nav.chirp_3hd": "Chirp 3 HD",
    "nav.chirp_3hd.desc": "حوّل النص إلى كلام عالي الدقة باستخدام Chirp 3.",
    "nav.vto": "القياس الافتراضي",
    "nav.vto.desc": "جرّب الملابس افتراضيًا.",
    "nav.motion_portraits": "صور شخصية متحركة",
    "nav.motion_portraits.desc": "حوّل صورة ثابتة إلى صورة شخصية متحركة.",
    "nav.character_consistency": "ثبات الشخصيات",
    "nav.character_consistency.desc": "حافظ على الشخصية نفسها عبر عدة صور ومقاطع فيديو.",
    "nav.shop_the_look": "تسوّق الإطلالة",
    "nav.shop_the_look.desc": "أنشئ تجربة «تسوّق الإطلالة» من عارضة وقطع ملابس.",
    "nav.storyboarder": "اللوحة القصصية",
    "nav.storyboarder.desc": "أنشئ لوحات قصصية لفيديو سردي متعدد المشاهد.",
    "nav.pixie_compositor": "Pixie Compositor",
    "nav.pixie_compositor.desc": "يساعدك Pixie على دمج الوسائط التوليدية.",
    "nav.labs": "التجارب",
    "nav.labs.desc": "أفكار تجريبية قيد التطوير.",
    "nav.about": "حول",
    "nav.about.desc": "معلومات عن GenMedia Creative Studio.",
    "nav.config": "الإعدادات",
    "nav.config.desc": "اضبط إعدادات التطبيق.",
    "nav.admin_users": "المستخدمون",
    "page.nano_banana.purpose": "أنشئ الصور وعدّلها انطلاقًا من وصف نصي وصورك الخاصة باستخدام Gemini.",
    "page.veo.purpose": "أنشئ مقاطع الفيديو أو عدّلها أو مدّدها أو ارفع دقتها باستخدام Gemini Omni أو Veo.",
    "page.voice.purpose": "حوّل النص المكتوب إلى كلام طبيعي بأكثر من 130 لغة.",
    "page.lyria.purpose": "ألّف الموسيقى والأغاني من وصف نصي، مع كلمات اختيارية.",
    "page.fashion.purpose": "ألبِس العارضة أي قطعة ملابس، أو نسّق إطلالة كاملة من الكتالوج.",
    "page.object_rotation.purpose": "حوّل صورة منتج واحدة إلى أربع لقطات استوديو وفيديو دوّار بزاوية 360°.",
    "page.interior_design.purpose": "حوّل مخطط الطابق إلى عرض ثلاثي الأبعاد، وأعد تصميم كل غرفة، وأنشئ جولة بالفيديو.",
    "page.starter_pack.purpose": "أنشئ مجموعة صور تناسب علامتك التجارية لمنتج أو حملة من فكرة واحدة.",
    "page.admin_users.purpose": "أضف الأشخاص وحدّد أدوارهم وأعد تعيين كلمات المرور. هذه الصفحة للمشرفين فقط.",
    "header.about": "حول هذه الصفحة",
    "menu.account": "الحساب",
    "menu.account_of": "الحساب: {name}",
    "menu.admin": "مشرف",
    "menu.user": "مستخدم",
    "menu.dark_mode": "الوضع الداكن",
    "menu.users": "المستخدمون",
    "menu.settings": "الإعدادات",
    "menu.account_settings": "إعدادات الحساب",
    "menu.about": "حول",
    "menu.sign_out": "تسجيل الخروج",
    "menu.guest": "ضيف",
    "menu.not_signed_in": "لم يتم تسجيل الدخول",
    "composer.placeholder": "صِف ما تريد إنشاءه…",
    "composer.enhance": "تحسين الوصف",
    "composer.send": "إنشاء",
    "composer.hint": "Enter للإنشاء · Shift+Enter لسطر جديد",
    "composer.hint_short": "Enter للإنشاء",
    "composer.clear": "مسح الوصف والنتائج",
    "composer.generating": "جارٍ الإنشاء",
    "composer.remove": "إزالة {label}",
    "results.recent": "الأحدث",
    "results.latest": "آخر نتيجة",
    "results.count_one": "عنصر واحد في هذه الجلسة",
    "results.count_other": "عدد العناصر في هذه الجلسة: {n}",
    "card.download": "تنزيل",
    "card.open": "فتح بحجم أكبر",
    "card.reuse": "إعادة استخدام الوصف",
    "card.video": "إنشاء فيديو من هذه الصورة",
    "card.extend": "تمديد هذا الفيديو",
    "card.edit": "تعديل هذه الصورة",
    "card.edit_video": "تعديل هذا الفيديو",
    "card.upscale": "رفع دقة هذا الفيديو",
    "card.actions": "الإجراءات",
    "card.play": "تشغيل: {name}",
    "card.open_item": "فتح: {name}",
    "card.generated": "عنصر مُنشأ",
    "progress.creating": "جارٍ إنشاء {media}",
    "progress.failed": "تعذّر إنشاء {media}",
    "progress.done": "تم",
    "progress.kept": "احتفظنا بالوصف والإعدادات.",
    "progress.usually": "عادةً ~{t}",
    "progress.generic_error": "حدث خطأ من جانبنا.",
    "progress.retry": "إعادة المحاولة",
    "progress.dismiss": "إغلاق",
    "progress.st_done": "(تم)",
    "progress.st_now": "(قيد التنفيذ)",
    "progress.st_failed": "(تعذّر)",
    "progress.aria": "تقدّم الإنشاء",
    "progress.elapsed": "الوقت المنقضي",
    "progress.estimated": "التقدّم المتوقع",
    "media.image": "الصورة",
    "media.video": "الفيديو",
    "media.audio": "الصوت",
    "media.music": "الموسيقى",
    "error.unknown": "خطأ غير معروف.",
    "error.credentials": (
        "تعذّر على الاستوديو تسجيل الدخول إلى Google Cloud. "
        "تحقّق من حساب الخدمة أو شغّل الأمر `gcloud auth application-default login`."
    ),
    "error.quota": "النموذج مشغول حاليًا (بلغت الحصة حدّها). انتظر دقيقة ثم حاول مجددًا.",
    "error.safety": "حظرت فلاتر الأمان هذا الطلب. جرّب إعادة صياغة الوصف.",
    "dialog.close": "إغلاق",
    "dialog.error_title": "خطأ في الإنشاء",
    "login.title": "تسجيل الدخول | GenMedia Studio",
    "login.visual_title": "أبدِع باستخدام نماذج Google للوسائط التوليدية.",
    "login.visual_body": "الصور والفيديو والموسيقى والكلام على Vertex AI، في استوديو واحد.",
    "login.visual_foot": "تبقى أعمالك داخل مشروعك الخاص على Google Cloud.",
    "login.tile_image": "الصور",
    "login.tile_image_sub": "Gemini Image و Imagen",
    "login.tile_video": "الفيديو",
    "login.tile_music": "الموسيقى",
    "login.tile_speech": "الكلام",
    "login.tile_speech_sub": "Gemini TTS و Chirp 3 HD",
    "login.welcome": "مرحبًا بعودتك",
    "login.lead": "سجّل الدخول إلى GenMedia Studio.",
    "login.email": "البريد الإلكتروني",
    "login.password": "كلمة المرور",
    "login.show": "إظهار",
    "login.hide": "إخفاء",
    "login.sr_password": " كلمة المرور",
    "login.submit": "تسجيل الدخول",
    "login.help": "ليس لديك حساب؟ اطلب من مشرف الاستوديو إضافتك.",
    "login.err_expired": "انتهت صلاحية هذه الصفحة. يُرجى تسجيل الدخول مجددًا.",
    "login.err_too_many": "محاولات كثيرة جدًا. انتظر 5 دقائق ثم حاول مجددًا.",
    "login.err_generic": "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
    "account.title": "إعدادات الحساب",
    "account.lead": "تم تسجيل الدخول باسم {email}.",
    "account.password_heading": "تغيير كلمة المرور",
    "account.current": "كلمة المرور الحالية",
    "account.new": "كلمة المرور الجديدة",
    "account.confirm": "تأكيد كلمة المرور الجديدة",
    "account.rule": "{n} أحرف على الأقل.",
    "account.submit": "تغيير كلمة المرور",
    "account.back": "العودة إلى الاستوديو",
    "account.changed": "تم تغيير كلمة المرور. تم تسجيل الخروج من الأجهزة الأخرى.",
    "account.err_expired": "انتهت صلاحية هذه الصفحة. يُرجى المحاولة مجددًا.",
    "account.err_current": "كلمة المرور الحالية غير صحيحة.",
    "account.err_mismatch": "كلمتا المرور الجديدتان غير متطابقتين.",
    "account.err_short": "استخدم {n} أحرف على الأقل.",
    "account.err_long": "استخدم 256 حرفًا كحد أقصى.",
    "account.err_same": "اختر كلمة مرور مختلفة عن كلمة المرور الحالية.",
    "account.err_too_many": "محاولات كثيرة جدًا. انتظر 5 دقائق ثم حاول مجددًا.",
    "admin.col_name": "الاسم",
    "admin.col_email": "البريد الإلكتروني",
    "admin.col_role": "الدور",
    "admin.col_status": "الحالة",
    "admin.col_created": "تاريخ الإنشاء",
    "admin.col_last": "آخر تسجيل دخول",
    "admin.col_actions": "الإجراءات",
    "admin.role_admin": "مشرف",
    "admin.role_user": "مستخدم",
    "admin.active": "نشط",
    "admin.disabled": "معطّل",
    "admin.never": "لم يسجّل بعد",
    "admin.you": " (أنت)",
    "admin.reset_password": "إعادة تعيين كلمة المرور",
    "admin.disable": "تعطيل",
    "admin.enable": "تفعيل",
    "admin.dismiss": "إغلاق",
    "admin.add_user": "إضافة مستخدم",
    "admin.add_help": "يسجّل المستخدم الدخول بهذا البريد الإلكتروني وكلمة المرور المؤقتة.",
    "admin.name": "الاسم",
    "admin.email": "البريد الإلكتروني",
    "admin.role": "الدور",
    "admin.role_user_long": "مستخدم: يمكنه استخدام الاستوديو",
    "admin.role_admin_long": "مشرف: يمكنه أيضًا إدارة المستخدمين",
    "admin.temp_password": "كلمة مرور مؤقتة",
    "admin.new": "توليد",
    "admin.cancel": "إلغاء",
    "admin.reset_help": "عيّن كلمة مرور جديدة للحساب {email}. ستنتهي جلساته الحالية.",
    "admin.new_password": "كلمة المرور الجديدة",
    "admin.search": "البحث بالاسم أو البريد الإلكتروني",
    "admin.no_match": "لا يوجد مستخدمون مطابقون.",
    "admin.no_users": "لا يوجد مستخدمون بعد.",
    "admin.count_one": "مستخدم واحد",
    "admin.count_other": "عدد المستخدمين: {n}",
    "admin.only_admins": "إدارة المستخدمين متاحة للمشرفين فقط.",
    # Home page
    "home.eyebrow": "Google Cloud · Vertex AI",
    "home.title": "الذكاء الاصطناعي الإبداعي من Google في استوديو واحد",
    "home.lede": "حوّل فكرة واحدة إلى صور وفيديو وصوت وموسيقى، أو إلى فيلم قصير مكتمل.",
    "home.create": "إنشاء",
    "home.create_sub": "أحدث نماذج Google للصور والفيديو والأفلام والصوت والموسيقى.",
    "home.demos": "عروض حسب القطاع",
    "home.demos_sub": "مسارات جاهزة لقطاعات التجزئة والمنتجات والعقارات والتسويق.",
    "home.badge.new": "جديد",
    "home.badge.story": "من الفكرة إلى الفيلم",
    "home.prompt.what": "ماذا تريد أن تنشئ",
    "home.prompt.describe": "صف فكرتك",
    "home.prompt.try": "جرّب:",
    "home.mode.image.label": "صورة",
    "home.mode.image.action": "أنشئ صورة",
    "home.mode.image.placeholder": "صف صورة لإنشائها أو تعديلها",
    "home.mode.image.ex1": "زجاجة عطر على حجر أسود مبلل بإضاءة استوديو",
    "home.mode.image.ex2": "حذاؤنا الرياضي في شارع بطوكيو ليلًا",
    "home.mode.video.label": "فيديو",
    "home.mode.video.action": "أنشئ فيديو",
    "home.mode.video.placeholder": "صف لقطة: الموضوع والحركة والكاميرا",
    "home.mode.video.ex1": "لقطة تقريب بطيئة لباريستا يرسم على القهوة",
    "home.mode.video.ex2": "لقطة بطائرة مسيّرة فوق طريق صحراوي عند الشروق",
    "home.mode.film.label": "فيلم",
    "home.mode.film.action": "أنشئ فيلمًا",
    "home.mode.film.placeholder": "فكرة واحدة لفيلم قصير، مع موسيقى وتعليق صوتي",
    "home.mode.film.ex1": "إعلان مدته 30 ثانية لدراجة كهربائية في المدينة",
    "home.mode.film.ex2": "حارس منارة يعثر على رسالة في زجاجة",
    "home.mode.voice.label": "صوت",
    "home.mode.voice.action": "أنشئ صوتًا",
    "home.mode.voice.placeholder": "اكتب نصًا لتحويله إلى كلام طبيعي",
    "home.mode.voice.ex1": "مرحبًا بكم في متجرنا. خصم 20% على كل شيء اليوم فقط.",
    "home.mode.voice.ex2": "شكرًا لاتصالك. طلبك في الطريق إليك.",
    "home.mode.music.label": "موسيقى",
    "home.mode.music.action": "أنشئ موسيقى",
    "home.mode.music.placeholder": "صف مقطوعة: الأجواء والآلات والإيقاع",
    "home.mode.music.ex1": "إيقاع لو-فاي دافئ مع بيانو هادئ، 80 نبضة في الدقيقة",
    "home.mode.music.ex2": "وتريات سينمائية ملهمة لإطلاق منتج",
}

_DICTS: dict[str, dict[str, str]] = {"en": EN, "ar": AR}


# --------------------------------------------------------------------------- #
# Strings pages pass to shared components, keyed by their English text.       #
# --------------------------------------------------------------------------- #
AR_TEXT: dict[str, str] = {
    # Composer placeholders and buttons (the 10 menu pages)
    "Describe the image you want to generate…": "صِف الصورة التي تريد إنشاءها…",
    "Describe the video you want to create…": "صِف الفيديو الذي تريد إنشاءه…",
    "Describe how the image should move…": "صِف كيف يجب أن تتحرك الصورة…",
    "Describe what happens between the first and last frame…": "صِف ما يحدث بين الإطار الأول والأخير…",
    "Describe a scene using your reference images…": "صِف مشهدًا باستخدام صورك المرجعية…",
    "Describe the change, e.g. make it night time…": "صِف التعديل، مثل: اجعله ليلًا…",
    "Describe what happens next…": "صِف ما يحدث بعد ذلك…",
    "No prompt needed: pick a resolution, then press Upscale": "لا حاجة إلى وصف: اختر الدقة ثم اضغط «رفع الدقة»",
    "Describe the music: genre, mood, instruments, tempo…": "صِف الموسيقى: النوع والمزاج والآلات والإيقاع…",
    "Type or paste the script to read aloud…": "اكتب النص المراد قراءته بصوت عالٍ أو الصقه…",
    "Write one line per speaker, like “Host: Hello there”…": "اكتب سطرًا لكل متحدث، مثل “Host: مرحبًا”…",
    "Enhance prompt with Gemini": "تحسين الوصف باستخدام Gemini",
    "Rewrite prompt with Gemini": "إعادة صياغة الوصف باستخدام Gemini",
    "Generate image": "إنشاء صورة",
    "Generate video": "إنشاء فيديو",
    "Edit video": "تعديل الفيديو",
    "Extend video": "تمديد الفيديو",
    "Upscale video": "رفع دقة الفيديو",
    "Generate speech": "إنشاء الكلام",
    "Generate music": "إنشاء موسيقى",
    "Clear script and results": "مسح النص والنتائج",
    "Clear prompt, lyrics and results": "مسح الوصف والكلمات والنتائج",
    "Clear prompt and results": "مسح الوصف والنتائج",
    "Enter to generate · Shift+Enter for a new line": "Enter للإنشاء · Shift+Enter لسطر جديد",
    "Enter to generate": "Enter للإنشاء",
    # Empty states
    "Your images will show up here": "ستظهر صورك هنا",
    "Describe a picture, or attach your own to edit, then press Enter.": "صِف صورة أو أرفق صورتك لتعديلها، ثم اضغط Enter.",
    "No images came back": "لم تصل أي صور",
    "Try a different prompt or another model.": "جرّب وصفًا مختلفًا أو نموذجًا آخر.",
    "Your videos will show up here": "ستظهر مقاطع الفيديو هنا",
    "Pick a mode, describe the shot, then press Enter.": "اختر وضعًا وصِف اللقطة، ثم اضغط Enter.",
    "Your audio will show up here": "سيظهر الصوت هنا",
    "Pick a voice and language, write a script, then press Enter.": "اختر صوتًا ولغة واكتب النص، ثم اضغط Enter.",
    "Your music will show up here": "ستظهر موسيقاك هنا",
    "Describe a sound or a song, then press Enter.": "صِف صوتًا أو أغنية، ثم اضغط Enter.",
    # Result grid titles
    "Recent": "الأحدث",
    "Latest": "آخر نتيجة",
    # Progress stages
    "Preparing": "التحضير",
    "Preparing prompt": "تحضير الوصف",
    "Preparing request": "تحضير الطلب",
    "Preparing the clip": "تحضير المقطع",
    "Preparing the photos": "تحضير الصور",
    "Reading your references": "قراءة الصور المرجعية",
    "Enhancing prompt": "تحسين الوصف",
    "Generating image": "إنشاء الصورة",
    "Generating video": "إنشاء الفيديو",
    "Editing video": "تعديل الفيديو",
    "Extending video": "تمديد الفيديو",
    "Upscaling video": "رفع دقة الفيديو",
    "Speaking": "توليد الكلام",
    "Composing": "التأليف",
    "Saving to library": "الحفظ في المكتبة",
    "Done": "تم",
    "Dressing the model with Virtual Try-On": "إلباس العارضة باستخدام Virtual Try-On",
    "Checking the fit with Gemini": "التحقق من الملاءمة باستخدام Gemini",
    "Reading the floor plan": "قراءة مخطط الطابق",
    "Building the 3D view with Gemini": "بناء العرض ثلاثي الأبعاد باستخدام Gemini",
    "Finding the rooms": "تحديد الغرف",
    "Reading the look": "قراءة الإطلالة",
    "Designing the kit with Gemini": "تصميم الحزمة باستخدام Gemini",
    "Reading the kit and model": "قراءة الحزمة والعارضة",
    "Styling the look with Gemini": "تنسيق الإطلالة باستخدام Gemini",
    "Describe the music first, then press Enter.": "صِف الموسيقى أولًا، ثم اضغط Enter.",
}

# Strings that embed a name: (English pattern, Arabic template).
_AR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Sending to (.+)$"), "الإرسال إلى {0}"),
    (
        re.compile(r"^Start each line with (.+): or (.+): · Enter to generate$"),
        "ابدأ كل سطر بـ {0}: أو {1}: · Enter للإنشاء",
    ),
)


# --------------------------------------------------------------------------- #
# Lookup                                                                      #
# --------------------------------------------------------------------------- #
def normalize_lang(value: str | None) -> str:
    """Map any value ("ar-QA", "AR", None) to one of LANGS."""
    v = (value or "").strip().lower()
    for lang in LANGS:
        if v == lang or v.startswith(lang + "-") or v.startswith(lang + "_"):
            return lang
    return DEFAULT_LANG


def lang_from_accept_language(header: str | None) -> str:
    """The first supported language in an Accept-Language header."""
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("ar"):
            return "ar"
        if tag.startswith("en"):
            return "en"
    return DEFAULT_LANG


def is_rtl(lang: str) -> bool:
    return lang in RTL_LANGS


def current_lang() -> str:
    """The language in AppState, or English outside a Mesop request."""
    try:
        import mesop as me  # pylint: disable=import-outside-toplevel

        from state.state import AppState  # pylint: disable=import-outside-toplevel

        lang = me.state(AppState).lang
    except Exception:  # noqa: BLE001  (no Mesop context: tests, FastAPI routes)
        return DEFAULT_LANG
    return lang if lang in LANGS else DEFAULT_LANG


def _format(text: str, fmt: dict) -> str:
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return text


def tl(lang: str, key: str, default: str | None = None, **fmt) -> str:
    """``t`` for an explicit language (pages rendered outside Mesop)."""
    text = _DICTS.get(lang, EN).get(key)
    if text is None:
        text = EN.get(key)
    if text is None:
        text = default if default is not None else key
    return _format(text, fmt)


def t(key: str, default: str | None = None, **fmt) -> str:
    """Text for `key` in the current language; English, then `default`, then the key."""
    return tl(current_lang(), key, default, **fmt)


def tr(key: str, english: str, **fmt) -> str:
    """`english` as given, or its translation under `key` in another language."""
    lang = current_lang()
    if lang != DEFAULT_LANG:
        text = _DICTS.get(lang, {}).get(key)
        if text is not None:
            return _format(text, fmt)
    return _format(english, fmt)


def tx_lang(lang: str, english: str) -> str:
    """Translate a page-supplied English string for `lang` (or return it)."""
    if lang != "ar" or not english:
        return english
    text = AR_TEXT.get(english)
    if text is not None:
        return text
    for pattern, template in _AR_PATTERNS:
        m = pattern.match(english)
        if m:
            return template.format(*m.groups())
    return english


def tx(english: str) -> str:
    """Translate a page-supplied English string for the current language."""
    return tx_lang(current_lang(), english)


def plural(key: str, n: int) -> str:
    """`key`_one or `key`_other, formatted with n."""
    return t(f"{key}_one" if n == 1 else f"{key}_other", n=n)


def route_key(route: str | None) -> str:
    """ "/nano-banana" -> "nano_banana" (the id used in nav.* and page.* keys)."""
    return (route or "").strip("/").replace("-", "_").lower()


# --------------------------------------------------------------------------- #
# State                                                                       #
# --------------------------------------------------------------------------- #
def apply_lang(state, lang: str, *, chosen: bool = True) -> str:
    """Set ``state.lang`` (and ``lang_chosen``). Returns the language applied."""
    state.lang = normalize_lang(lang)
    if chosen:
        state.lang_chosen = True
    return state.lang


def other_lang(lang: str) -> str:
    return "en" if lang == "ar" else "ar"
