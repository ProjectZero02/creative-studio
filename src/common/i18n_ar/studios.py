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
"""Arabic for the studios pages, keyed by the exact English text (see common/i18n_mesop.py).

Image Studio (/nano-banana), Video Studio (/veo), Voice (/voice), Music
(/lyria), and the Home box settings (services/studio_options.py).
Product and model names stay in Latin script.
"""

# English text -> Arabic.
AR_TEXT: dict[str, str] = {
    # ------------------------------------------------------------------ shared
    "Close": "إغلاق",
    "Cancel": "إلغاء",
    "Add": "إضافة",
    "Current Settings": "الإعدادات الحالية",
    "Something went wrong": "حدث خطأ",
    "Write a prompt first, then enhance it.": "اكتب الوصف أولًا، ثم حسّنه.",
    "Please enter a prompt.": "يُرجى كتابة وصف.",
    "Unknown error": "خطأ غير معروف",
    "Choose from library": "اختيار من المكتبة",
    "Choose from Library": "اختيار من المكتبة",
    "Upload an image": "رفع صورة",
    # Section titles rendered as markdown ("## " + title)
    "## Latest": "## آخر نتيجة",
    "## Keep going": "## تابِع",
    "## Advanced settings": "## إعدادات متقدمة",
    "## Speakers": "## المتحدثون",
    "## Direction": "## التوجيه",
    "## Pronunciations": "## النطق",
    "## Lyrics (optional)": "## الكلمات (اختياري)",
    # ------------------------------------------------------- composer chips
    "Model": "النموذج",
    "Aspect ratio": "نسبة الأبعاد",
    "Resolution": "الدقة",
    "Image size": "حجم الصورة",
    "Length": "المدة",
    "Number of images": "عدد الصور",
    "Number of videos": "عدد الفيديوهات",
    "Number of tracks": "عدد المقاطع",
    "Voice": "الصوت",
    "Language": "اللغة",
    "Speaking style": "أسلوب الأداء",
    "Pace": "السرعة",
    "Auto": "تلقائي",
    "Square": "مربع",
    "Landscape": "أفقي",
    "Portrait": "عمودي",
    "Classic": "كلاسيكي",
    "Classic portrait": "كلاسيكي عمودي",
    "Cinematic": "سينمائي",
    "Brand": "العلامة",
    "Apply my brand: colours and tone": "تطبيق علامتي التجارية: الألوان والأسلوب",
    "Your brand is empty. Set it up on the My brand page first.": (
        "علامتك التجارية فارغة. أعدّها أولًا في صفحة «علامتي التجارية»."
    ),
    "Gemini Omni always adds sound": "يضيف Gemini Omni الصوت دائمًا",
    "Sound: always on": "الصوت: مفعّل دائمًا",
    "Generate audio": "إنشاء الصوت",
    "Audio": "الصوت",
    "Advanced settings: seed, things to avoid, people": "إعدادات متقدمة: البذرة وما يجب تجنبه والأشخاص",
    "Advanced": "متقدم",
    "Dialogue": "حوار",
    "Dialogue: two speakers with their own voices": "حوار: متحدثان لكل منهما صوت",
    "Direction": "التوجيه",
    "Direction: describe the delivery in your own words": "التوجيه: صِف الأداء بكلماتك",
    "Pronunciations": "النطق",
    "Custom pronunciations for names and terms": "نطق مخصص للأسماء والمصطلحات",
    "Lyrics": "الكلمات",
    "Lyrics: add words to sing (optional)": "الكلمات: أضف كلمات للغناء (اختياري)",
    "Songs with lyrics": "أغانٍ بكلمات",
    "Instrumental clips": "مقاطع موسيقية بلا كلمات",
    "Newest · default": "الأحدث · افتراضي",
    "Cloud TTS · custom pronunciations": "Cloud TTS · نطق مخصص",
    # ---------------------------------------------------------- Image Studio
    "Image Studio": "استوديو الصور",
    "Add reference images or files": "إضافة صور مرجعية أو ملفات",
    "Generated image": "صورة مُنشأة",
    "Generated image, full size": "صورة مُنشأة بالحجم الكامل",
    "Edit this image": "تعديل هذه الصورة",
    "Make a video": "إنشاء فيديو",
    "Edit actions": "إجراءات التعديل",
    "Creative actions": "إجراءات إبداعية",
    "Custom actions": "إجراءات مخصصة",
    "Suggesting…": "جارٍ الاقتراح…",
    "Suggest edits": "اقتراح تعديلات",
    "Sources": "المصادر",
    "Source": "المصدر",
    "Please select an image to transform.": "يُرجى اختيار صورة لتحويلها.",
    "Invalid transformation data.": "بيانات التحويل غير صالحة.",
    "No image available to suggest transformations for.": "لا توجد صورة لاقتراح تعديلات عليها.",
    "Please upload or select an image first.": "يُرجى رفع صورة أو اختيارها أولًا.",
    "Please select an image to continue with.": "يُرجى اختيار صورة للمتابعة.",
    "No images returned.": "لم تصل أي صور.",
    "No images were generated, but the attempt was logged to the library.": (
        "لم تُنشأ أي صور، لكن المحاولة سُجّلت في المكتبة."
    ),
    "This image isn't saved in Cloud Storage yet.": "هذه الصورة غير محفوظة في Cloud Storage بعد.",
    # Image presets (config/banana_presets.py)
    "rotate left": "تدوير لليسار",
    "rotate right": "تدوير لليمين",
    "remove background": "إزالة الخلفية",
    "zoom out": "تصغير",
    "blur": "تمويه",
    "overhead": "من الأعلى",
    "side": "من الجانب",
    "close up": "لقطة قريبة",
    "isometric": "متساوي القياس",
    "line": "رسم خطي",
    "hologram": "صورة ثلاثية الأبعاد",
    "1990's grunge": "أسلوب التسعينيات",
    "alien": "كائن فضائي",
    "hairstyle-bob": "قصة شعر بوب",
    "1/7th figurine": "مجسّم بمقياس 1/7",
    "restore & colorize": "ترميم وتلوين",
    "80's highschool headshot": "صورة مدرسية من الثمانينيات",
    "labubu": "Labubu",
    "professional headshot": "صورة شخصية احترافية",
    "trollify": "شخصية Troll",
    # Info dialog (config/about_content.json, also on /about)
    "About Gemini  Image Generation": "حول إنشاء الصور باستخدام Gemini",
    "Gemini Image Generation - Nano-banana\n\nGenerate, transform and edit images with simple text prompts, or combine multiple images to create something new. All in Gemini.\n\nLearn more about [Gemini 3 Pro Image](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-pro-image) on Gemini Enterprise Agent Platform.\n\nLearn more about [Search Grounding](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/grounding-with-google-search#grounding_support) with Gemini 3 Pro Image, see the [Service Specific Terms](https://cloud.google.com/terms/service-terms).": (
        "إنشاء الصور باستخدام Gemini (Nano Banana)\n\n"
        "أنشئ الصور وحوّلها وعدّلها بأوصاف نصية بسيطة، أو اجمع عدة صور لصنع شيء جديد. كل ذلك في Gemini.\n\n"
        "اعرف المزيد عن [Gemini 3 Pro Image](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-pro-image) على Gemini Enterprise Agent Platform.\n\n"
        "اعرف المزيد عن [الاستناد إلى بحث Google](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/grounding-with-google-search#grounding_support) مع Gemini 3 Pro Image، وراجع [شروط الخدمة الخاصة](https://cloud.google.com/terms/service-terms)."
    ),
    # ---------------------------------------------------------- Video Studio
    "Video Studio": "استوديو الفيديو",
    # Mode tabs (config/video_studio_models.STUDIO_MODE_LABELS)
    "Text": "النص",
    "Image": "الصورة",
    "First + last frame": "الإطار الأول والأخير",
    "References": "المراجع",
    "Extend": "تمديد",
    "Upscale": "رفع الدقة",
    "Video to edit": "الفيديو المراد تعديله",
    "Video to extend": "الفيديو المراد تمديده",
    "Video to upscale": "الفيديو المراد رفع دقته",
    "Input video": "الفيديو المُدخل",
    "Remove this video": "إزالة هذا الفيديو",
    "Upload video": "رفع فيديو",
    "Or hover a clip under Recent and choose “Edit this video”.": (
        "أو مرّر المؤشر على مقطع في «الأحدث» واختر «تعديل هذا الفيديو»."
    ),
    "Or hover a clip under Recent and choose “Extend this video”.": (
        "أو مرّر المؤشر على مقطع في «الأحدث» واختر «تمديد هذا الفيديو»."
    ),
    "Or hover a clip under Recent and choose “Upscale this video”.": (
        "أو مرّر المؤشر على مقطع في «الأحدث» واختر «رفع دقة هذا الفيديو»."
    ),
    "Or hover a clip under Recent and choose “Use this video”.": (
        "أو مرّر المؤشر على مقطع في «الأحدث» واختر «استخدام هذا الفيديو»."
    ),
    "First frame": "الإطار الأول",
    "Last frame": "الإطار الأخير",
    "Style reference": "مرجع الأسلوب",
    "Close advanced settings": "إغلاق الإعدادات المتقدمة",
    "Avoid in the video (negative prompt)": "ما يجب تجنبه في الفيديو (وصف سلبي)",
    "Seed (0 = random)": "البذرة (0 = عشوائي)",
    "Steers the result. Veo 3.x can't repeat a result exactly while prompt enhancement is on.": (
        "توجّه النتيجة. لا يكرر Veo 3.x النتيجة نفسها تمامًا أثناء تفعيل تحسين الوصف."
    ),
    "People in video": "الأشخاص في الفيديو",
    "Allow (All ages)": "السماح (كل الأعمار)",
    "Allow (Adults only)": "السماح (البالغون فقط)",
    "Don't Allow": "عدم السماح",
    "Let Veo enhance the prompt": "السماح لـ Veo بتحسين الوصف",
    "Let Veo enhance the prompt (always on for this model)": (
        "السماح لـ Veo بتحسين الوصف (مفعّل دائمًا لهذا النموذج)"
    ),
    "Convert to GIF": "تحويل إلى GIF",
    "Video as GIF:": "الفيديو بصيغة GIF:",
    "extend": "تمديد",
    "Extending video...": "جارٍ تمديد الفيديو...",
    "Please enter a prompt for the extension.": "يُرجى كتابة وصف للتمديد.",
    "Video extension is not supported by the current model.": "النموذج الحالي لا يدعم تمديد الفيديو.",
    "No video selected to extend.": "لم يتم اختيار فيديو لتمديده.",
    "Failed to start generation job": "تعذّر بدء مهمة الإنشاء",
    "Unknown error during generation.": "خطأ غير معروف أثناء الإنشاء.",
    "Failed to start extension job": "تعذّر بدء مهمة التمديد",
    "Unknown error during extension.": "خطأ غير معروف أثناء التمديد.",
    "Could not save the job record. Check Firestore access and Google Cloud credentials.": (
        "تعذّر حفظ سجل المهمة. تحقّق من الوصول إلى Firestore وبيانات اعتماد Google Cloud."
    ),
    # Missing media (models/omni.find_missing_required_media)
    "Image-to-Video requires a reference image.": "وضع «صورة» يحتاج إلى صورة مرجعية.",
    "First/Last Frame requires both a first and a last frame image.": (
        "وضع «الإطار الأول والأخير» يحتاج إلى صورتين: الإطار الأول والأخير."
    ),
    "Reference-to-Video requires at least one reference image.": (
        "وضع «مراجع» يحتاج إلى صورة مرجعية واحدة على الأقل."
    ),
    "Video editing requires a base video to edit.": "تعديل الفيديو يحتاج إلى فيديو لتعديله.",
    "Extend requires a base video to extend.": "التمديد يحتاج إلى فيديو لتمديده.",
    "Upscale requires a video to upscale.": "رفع الدقة يحتاج إلى فيديو لرفع دقته.",
    # Info dialog
    "About Video Studio": "حول استوديو الفيديو",
    "Video Studio uses **Gemini Omni** by default: text, image, first + last frame and up to 10 reference images, plus editing, extending and upscaling a video, with generated sound.": (
        "يستخدم استوديو الفيديو **Gemini Omni** افتراضيًا: من نص أو صورة أو الإطار الأول والأخير "
        "أو حتى 10 صور مرجعية، إضافة إلى تعديل الفيديو وتمديده ورفع دقته، مع صوت مُنشأ."
    ),
    "Video Studio uses **Gemini Omni** by default: text, image, first + last frame and up to 10 reference images, plus editing, extending and upscaling a video, with generated sound. Pick a **Veo** model in the Model chip to use Veo instead.": (
        "يستخدم استوديو الفيديو **Gemini Omni** افتراضيًا: من نص أو صورة أو الإطار الأول والأخير "
        "أو حتى 10 صور مرجعية، إضافة إلى تعديل الفيديو وتمديده ورفع دقته، مع صوت مُنشأ. "
        "لاستخدام Veo، اختر نموذج **Veo** من شريحة النموذج."
    ),
    "The **Veo** page is for advanced video generation. You can create videos using several modes:\n*   **Text-to-Video**: Create a video from a descriptive text prompt.\n*   **Image-to-Video**: Animate a single static image.\n*   **First/Last Frame**: Generate the video motion between a starting image and an ending image.\n*   **Reference-to-Video**: Generate a video based on multiple asset images and an optional style reference image.\n\n**Available Models:**\n*   Veo 2\n*   Veo 3 & Veo 3 Fast\n*   Veo 3.1 & Veo 3.1 Fast\n\n[Learn more about Veo on Gemini Enterprise Agent Platform](https://cloud.google.com/vertex-ai/docs/generative-ai/video/overview)": (
        "صفحة **Veo** لإنشاء الفيديو المتقدم. يمكنك إنشاء الفيديو بعدة أوضاع:\n"
        "*   **نص إلى فيديو**: أنشئ فيديو من وصف نصي.\n"
        "*   **صورة إلى فيديو**: حرّك صورة ثابتة واحدة.\n"
        "*   **الإطار الأول والأخير**: أنشئ الحركة بين صورة البداية وصورة النهاية.\n"
        "*   **مراجع إلى فيديو**: أنشئ فيديو من عدة صور مرجعية وصورة أسلوب اختيارية.\n\n"
        "**النماذج المتاحة:**\n*   Veo 2\n*   Veo 3 و Veo 3 Fast\n*   Veo 3.1 و Veo 3.1 Fast\n\n"
        "[اعرف المزيد عن Veo على Gemini Enterprise Agent Platform](https://cloud.google.com/vertex-ai/docs/generative-ai/video/overview)"
    ),
    # ----------------------------------------------------------------- Voice
    "Speakers": "المتحدثون",
    "Turn off dialogue": "إيقاف الحوار",
    "First speaker's name": "اسم المتحدث الأول",
    "Second speaker's name": "اسم المتحدث الثاني",
    "Pick each speaker's voice with the chips above. Lines without a name continue the previous speaker.": (
        "اختر صوت كل متحدث من الشرائح أعلاه. السطر بلا اسم يكمل المتحدث السابق."
    ),
    "Close direction": "إغلاق التوجيه",
    "How should it sound? e.g. “excited, like announcing a winner”": (
        "كيف يجب أن يبدو؟ مثل: «متحمس، كأنه يعلن فائزًا»"
    ),
    "You can also put tags like [laughing] or [sigh] right in the script.": (
        "يمكنك أيضًا وضع وسوم مثل [laughing] أو [sigh] داخل النص مباشرة."
    ),
    "Close pronunciations": "إغلاق النطق",
    "Word or phrase": "الكلمة أو العبارة",
    "Say it as": "تُنطق هكذا",
    "Alphabet": "الأبجدية الصوتية",
    "Example: “Mesop” → “m e s O p” in X-SAMPA. Applies to this script only.": (
        "مثال: «Mesop» ← «m e s O p» في X-SAMPA. ينطبق على هذا النص فقط."
    ),
    "Japanese": "اليابانية",
    # Voice styles and paces, from config/voice.py
    "Natural": "طبيعي",
    "Warm": "دافئ",
    "Cheerful": "مبتهج",
    "Calm": "هادئ",
    "Newsreader": "مذيع أخبار",
    "Storyteller": "راوٍ",
    "Advert": "إعلان",
    "Whisper": "همس",
    "Slow": "بطيء",
    "Normal pace": "سرعة عادية",
    "Brisk": "سريع قليلًا",
    "Fast": "سريع",
    # Info dialogs (config/about_content.json)
    "Gemini TTS": "Gemini TTS",
    "The **Gemini Text-to-Speech** page uses Google's latest generative TTS models to create high-quality, natural-sounding audio from text.\n\n- **Text to Synthesize**: The raw text to be spoken.\n- **Voice Prompt**: A prompt to guide the style, tone, and emotion of the voice.\n- **Model**: Choose between faster or higher-quality models.\n- **Voice**: Select from a variety of distinct voices.\n\nText-to-Speech Gemini-TTS is the latest evolution of our Text-to-Speech technology that's moving beyond just naturalness to giving granular control over generated audio using text-based prompts. Using Gemini-TTS, you can synthesize speech from short snippets to long-form narratives, precisely dictating style, accent, pace, tone, and even emotional expression, all steerable through natural-language prompts.\n\n**Technical Audio Metrics:**\n*   **Duration**: The total length of the generated audio clip in seconds.\n*   **Tempo**: The estimated speed of speech, measured in beats per minute (BPM).\n*   **Mean Pitch**: The average fundamental frequency of the voice, indicating how high or low it sounds overall.\n*   **Pitch Range**: The difference between the highest and lowest pitch, showing the dynamic range of the voice.\n*   **Pitch Std Dev**: A measure of pitch variation; higher values often indicate more expressive speech.\n*   **Jitter**: Micro-variations in pitch that can affect perceived voice roughness or naturalness.\n*   **Shimmer**: Micro-variations in volume that can also contribute to perceived voice quality.\n*   **HNR (Harmonics-to-Noise Ratio)**: A measure of voice purity; higher values generally mean clearer, less breathy speech.\n\n[Learn more about Gemini-TTS on Gemini Enterprise Agent Platform](https://cloud.google.com/text-to-speech/docs/gemini-tts)": (
        "تستخدم صفحة **تحويل النص إلى كلام باستخدام Gemini** أحدث نماذج Google التوليدية لإنشاء صوت طبيعي عالي الجودة من النص.\n\n"
        "- **النص**: الكلمات التي تُقال.\n"
        "- **توجيه الصوت**: وصف يوجّه أسلوب الصوت ونبرته وعاطفته.\n"
        "- **النموذج**: اختر بين نماذج أسرع أو أعلى جودة.\n"
        "- **الصوت**: اختر من أصوات متنوعة.\n\n"
        "Gemini-TTS هو أحدث تطور لتقنية تحويل النص إلى كلام، ويمنحك تحكمًا دقيقًا في الصوت المُنشأ بأوصاف نصية: "
        "من مقاطع قصيرة إلى سرد طويل، مع التحكم في الأسلوب واللهجة والسرعة والنبرة والعاطفة.\n\n"
        "**مقاييس الصوت التقنية:**\n"
        "*   **المدة**: طول المقطع الصوتي بالثواني.\n"
        "*   **الإيقاع**: سرعة الكلام التقديرية بالنبضات في الدقيقة (BPM).\n"
        "*   **متوسط طبقة الصوت**: متوسط التردد الأساسي للصوت، ويدل على حدته أو عمقه.\n"
        "*   **مدى طبقة الصوت**: الفرق بين أعلى طبقة وأدناها.\n"
        "*   **الانحراف المعياري لطبقة الصوت**: مقدار تغيّر الطبقة؛ القيم الأعلى تعني كلامًا أكثر تعبيرًا.\n"
        "*   **Jitter**: تغيّرات دقيقة في الطبقة قد تؤثر في خشونة الصوت أو طبيعيته.\n"
        "*   **Shimmer**: تغيّرات دقيقة في شدة الصوت تؤثر في جودته.\n"
        "*   **HNR (نسبة التوافقيات إلى الضوضاء)**: مقياس لنقاء الصوت؛ القيم الأعلى تعني صوتًا أوضح.\n\n"
        "[اعرف المزيد عن Gemini-TTS على Gemini Enterprise Agent Platform](https://cloud.google.com/text-to-speech/docs/gemini-tts)"
    ),
    "Chirp3 HD": "Chirp 3 HD",
    "**Chirp 3** represents the latest generation of Google's Text-to-Speech technology, powered by large language models (LLMs). These high-definition voices are designed to deliver an unparalleled level of realism and emotional resonance, making them sound incredibly natural.\n\nYou can use Chirp 3 to:\n*   Create realistic, conversational audio for applications.\n*   Generate speech in dozens of languages and regions.\n*   Control the pace, add pauses, and specify custom pronunciations.\n\n[Learn more about Chirp 3 HD on Gemini Enterprise Agent Platform](https://cloud.google.com/text-to-speech/docs/chirp3-hd)": (
        "**Chirp 3** هو أحدث جيل من تقنية Google لتحويل النص إلى كلام، ويعمل بالنماذج اللغوية الكبيرة. "
        "صُممت هذه الأصوات عالية الدقة لتبدو واقعية وطبيعية جدًا.\n\n"
        "يمكنك استخدام Chirp 3 من أجل:\n"
        "*   إنشاء صوت حواري واقعي للتطبيقات.\n"
        "*   إنشاء الكلام بعشرات اللغات والمناطق.\n"
        "*   التحكم في السرعة وإضافة وقفات وتحديد نطق مخصص.\n\n"
        "[اعرف المزيد عن Chirp 3 HD على Gemini Enterprise Agent Platform](https://cloud.google.com/text-to-speech/docs/chirp3-hd)"
    ),
    # Language names (config/gemini_tts.py: Gemini TTS and Chirp 3 HD)
    "Afrikaans (South Africa)": "الأفريكانية (جنوب أفريقيا)",
    "Albanian (Albania)": "الألبانية (ألبانيا)",
    "Amharic (Ethiopia)": "الأمهرية (إثيوبيا)",
    "Arabic (Egypt)": "العربية (مصر)",
    "Arabic (Generic)": "العربية (عامة)",
    "Arabic (World)": "العربية (عامة)",
    "Armenian (Armenia)": "الأرمنية (أرمينيا)",
    "Azerbaijani (Azerbaijan)": "الأذربيجانية (أذربيجان)",
    "Bangla (Bangladesh)": "البنغالية (بنغلاديش)",
    "Basque (Spain)": "الباسكية (إسبانيا)",
    "Belarusian (Belarus)": "البيلاروسية (بيلاروسيا)",
    "Bengali (India)": "البنغالية (الهند)",
    "Bulgarian (Bulgaria)": "البلغارية (بلغاريا)",
    "Burmese (Myanmar)": "البورمية (ميانمار)",
    "Catalan (Spain)": "الكتالونية (إسبانيا)",
    "Cebuano (Philippines)": "السيبوانية (الفلبين)",
    "Chinese, Mandarin (China)": "الصينية الماندرين (الصين)",
    "Chinese, Mandarin (Taiwan)": "الصينية الماندرين (تايوان)",
    "Mandarin Chinese (China)": "الصينية الماندرين (الصين)",
    "Croatian (Croatia)": "الكرواتية (كرواتيا)",
    "Czech (Czech Republic)": "التشيكية (التشيك)",
    "Danish (Denmark)": "الدنماركية (الدنمارك)",
    "Dutch (Belgium)": "الهولندية (بلجيكا)",
    "Dutch (Netherlands)": "الهولندية (هولندا)",
    "English (Australia)": "الإنجليزية (أستراليا)",
    "English (India)": "الإنجليزية (الهند)",
    "English (United Kingdom)": "الإنجليزية (المملكة المتحدة)",
    "English (United States)": "الإنجليزية (الولايات المتحدة)",
    "Estonian (Estonia)": "الإستونية (إستونيا)",
    "Filipino (Philippines)": "الفلبينية (الفلبين)",
    "Finnish (Finland)": "الفنلندية (فنلندا)",
    "French (Canada)": "الفرنسية (كندا)",
    "French (France)": "الفرنسية (فرنسا)",
    "Galician (Spain)": "الجاليكية (إسبانيا)",
    "Georgian (Georgia)": "الجورجية (جورجيا)",
    "German (Germany)": "الألمانية (ألمانيا)",
    "Greek (Greece)": "اليونانية (اليونان)",
    "Gujarati (India)": "الغوجاراتية (الهند)",
    "Haitian Creole (Haiti)": "الكريولية الهايتية (هايتي)",
    "Hebrew (Israel)": "العبرية (إسرائيل)",
    "Hindi (India)": "الهندية (الهند)",
    "Hungarian (Hungary)": "المجرية (المجر)",
    "Icelandic (Iceland)": "الآيسلندية (آيسلندا)",
    "Indonesian (Indonesia)": "الإندونيسية (إندونيسيا)",
    "Italian (Italy)": "الإيطالية (إيطاليا)",
    "Japanese (Japan)": "اليابانية (اليابان)",
    "Javanese (Java)": "الجاوية (جاوة)",
    "Kannada (India)": "الكانادا (الهند)",
    "Konkani (India)": "الكونكانية (الهند)",
    "Korean (South Korea)": "الكورية (كوريا الجنوبية)",
    "Lao (Laos)": "اللاوية (لاوس)",
    "Latin (Vatican City)": "اللاتينية (الفاتيكان)",
    "Latvian (Latvia)": "اللاتفية (لاتفيا)",
    "Lithuanian (Lithuania)": "الليتوانية (ليتوانيا)",
    "Luxembourgish (Luxembourg)": "اللوكسمبورغية (لوكسمبورغ)",
    "Macedonian (North Macedonia)": "المقدونية (مقدونيا الشمالية)",
    "Maithili (India)": "الميثيلية (الهند)",
    "Malagasy (Madagascar)": "الملغاشية (مدغشقر)",
    "Malay (Malaysia)": "الملايوية (ماليزيا)",
    "Malayalam (India)": "المالايالامية (الهند)",
    "Marathi (India)": "الماراثية (الهند)",
    "Mongolian (Mongolia)": "المنغولية (منغوليا)",
    "Nepali (Nepal)": "النيبالية (نيبال)",
    "Norwegian Bokmål (Norway)": "النرويجية بوكمال (النرويج)",
    "Norwegian, Bokmål (Norway)": "النرويجية بوكمال (النرويج)",
    "Norwegian, Nynorsk (Norway)": "النرويجية نينوشك (النرويج)",
    "Odia (India)": "الأوديا (الهند)",
    "Pashto (Afghanistan)": "البشتو (أفغانستان)",
    "Persian (Iran)": "الفارسية (إيران)",
    "Polish (Poland)": "البولندية (بولندا)",
    "Portuguese (Brazil)": "البرتغالية (البرازيل)",
    "Portuguese (Portugal)": "البرتغالية (البرتغال)",
    "Punjabi (India)": "البنجابية (الهند)",
    "Romanian (Romania)": "الرومانية (رومانيا)",
    "Russian (Russia)": "الروسية (روسيا)",
    "Serbian (Serbia)": "الصربية (صربيا)",
    "Sindhi (India)": "السندية (الهند)",
    "Sinhala (Sri Lanka)": "السنهالية (سريلانكا)",
    "Slovak (Slovakia)": "السلوفاكية (سلوفاكيا)",
    "Slovenian (Slovenia)": "السلوفينية (سلوفينيا)",
    "Spanish (Latin America)": "الإسبانية (أمريكا اللاتينية)",
    "Spanish (Mexico)": "الإسبانية (المكسيك)",
    "Spanish (Spain)": "الإسبانية (إسبانيا)",
    "Spanish (United States)": "الإسبانية (الولايات المتحدة)",
    "Swahili (Kenya)": "السواحيلية (كينيا)",
    "Swedish (Sweden)": "السويدية (السويد)",
    "Tamil (India)": "التاميلية (الهند)",
    "Telugu (India)": "التيلوغوية (الهند)",
    "Thai (Thailand)": "التايلاندية (تايلاند)",
    "Turkish (Turkey)": "التركية (تركيا)",
    "Ukrainian (Ukraine)": "الأوكرانية (أوكرانيا)",
    "Urdu (India)": "الأردية (الهند)",
    "Urdu (Pakistan)": "الأردية (باكستان)",
    "Vietnamese (Vietnam)": "الفيتنامية (فيتنام)",
    # ----------------------------------------------------------------- Music
    "Music": "الموسيقى",
    "Add a reference image": "إضافة صورة مرجعية",
    "Hide lyrics": "إخفاء الكلمات",
    "Write the words to sing, or leave this empty for music without words.": (
        "اكتب الكلمات المراد غناؤها، أو اتركها فارغة لموسيقى بلا كلمات."
    ),
    "Gemini can draft lyrics from your music prompt.": "يمكن لـ Gemini كتابة مسودة كلمات من وصف الموسيقى.",
    "Writing lyrics…": "جارٍ كتابة الكلمات…",
    "Write lyrics with Gemini": "كتابة الكلمات باستخدام Gemini",
    "Generated text": "النص المُنشأ",
    "Analyzing the track with Gemini…": "جارٍ تحليل المقطع باستخدام Gemini…",
    "Please enter a prompt before rewriting.": "يُرجى كتابة وصف قبل إعادة الصياغة.",
    "Please enter a music prompt to generate lyrics from.": "يُرجى كتابة وصف للموسيقى لإنشاء الكلمات منه.",
    "Music rewriter in progress...": "جارٍ إعادة صياغة وصف الموسيقى...",
    "Generating music with Lyria...": "جارٍ إنشاء الموسيقى باستخدام Lyria...",
    "Analysis returned no result.": "لم يُرجع التحليل أي نتيجة.",
    "Music Critic": "تقييم الموسيقى",
    "Description": "الوصف",
    "Prompt Alignment": "مطابقة الوصف",
    "Audio Analysis Failed": "تعذّر تحليل الصوت",
    "Technical Audio Metrics": "مقاييس الصوت التقنية",
    "About Lyria": "حول Lyria",
    "The **Lyria** page lets you generate musical scores. Provide a prompt describing the mood, genre, or instruments you want to hear. With Lyria 3, you can also optionally provide lyrics and image prompts.\n\n**Available Models:**\n*   Lyria 2\n*   Lyria 3 Clip\n*   Lyria 3 Pro\n\n[Learn more about Lyria on Gemini Enterprise Agent Platform](https://cloud.google.com/vertex-ai/docs/generative-ai/audio/overview)": (
        "تتيح لك صفحة **Lyria** إنشاء مقطوعات موسيقية. اكتب وصفًا للمزاج أو النوع أو الآلات التي تريد سماعها. "
        "مع Lyria 3 يمكنك أيضًا إضافة كلمات وصورة مرجعية.\n\n"
        "**النماذج المتاحة:**\n*   Lyria 2\n*   Lyria 3 Clip\n*   Lyria 3 Pro\n\n"
        "[اعرف المزيد عن Lyria على Gemini Enterprise Agent Platform](https://cloud.google.com/vertex-ai/docs/generative-ai/audio/overview)"
    ),
    # ------------------------------------------- Home box (studio_options)
    "On": "تشغيل",
    "Off": "إيقاف",
    "Shape": "الشكل",
    "Quality": "الجودة",
    "Sound": "الصوت",
    "Style": "الأسلوب",
    "Number": "العدد",
    "Brand colours": "ألوان العلامة",
    "Search grounding": "الاستناد إلى البحث",
    "Thinking": "التفكير",
    "Mode": "الوضع",
    "Avoid": "تجنّب",
    "Seed": "البذرة",
    "People": "الأشخاص",
    "Improve prompt": "تحسين الوصف",
    "Lyrics text": "نص الكلمات",
    "Instrumental": "موسيقى فقط",
    "Two speakers": "متحدثان",
    "Speaker 1": "المتحدث 1",
    "Speaker 2": "المتحدث 2",
    "Voice 2": "الصوت 2",
    "Start from": "البدء من",
    "Video engine": "محرك الفيديو",
    "Pacing": "الإيقاع",
    "Who speaks": "من يتحدث",
    "Camera": "الكاميرا",
    "Scenes": "المشاهد",
    "Scene length": "مدة المشهد",
    "With sound": "مع صوت",
    "No sound": "بدون صوت",
    "Look things up on Google first": "البحث في Google أولًا",
    "High": "عالٍ",
    "Minimal": "أدنى",
    "Style image": "صورة الأسلوب",
    "What to leave out": "ما يجب استبعاده",
    "0 = random": "0 = عشوائي",
    "Your lyrics": "كلماتك",
    "Reference image": "صورة مرجعية",
    "How to say it": "طريقة القول",
    "One per line: word=how to say it": "سطر لكل كلمة: الكلمة=طريقة نطقها",
    "Idea": "الفكرة",
    "Script": "النص",
}

# (regex on the English text, Arabic template with {0}, {1}...) for text built at runtime.
PATTERNS: list[tuple[str, str]] = [
    # Counts and durations in chips and menus
    (r"^1 images?$", "صورة واحدة"),
    (r"^2 images$", "صورتان"),
    (r"^(\d+) images$", "{0} صور"),
    (r"^1 videos?$", "فيديو واحد"),
    (r"^2 videos$", "فيديوهان"),
    (r"^(\d+) videos$", "{0} فيديوهات"),
    (r"^1 tracks?$", "مقطع واحد"),
    (r"^2 tracks$", "مقطعان"),
    (r"^(\d+) tracks$", "{0} مقاطع"),
    (r"^(\d+(?:\.\d+)?)s$", "{0} ث"),
    (r"^(\d+) seconds$", "{0} ثوانٍ"),
    (r"^Usually ~(\d+)s$", "عادةً ~{0} ث"),
    (
        r"^Edit, extend, upscale · Usually ~(\d+)s$",
        "تعديل وتمديد ورفع الدقة · عادةً ~{0} ث",
    ),
    (r"^Made in ([\d.]+)s$", "أُنشئت في {0} ث"),
    (r"^More styles \((\d+)\)$", "أنماط أخرى ({0})"),
    (r"^Subjects \(up to (\d+)\)$", "العناصر (حتى {0})"),
    (r"^Pronunciations \((\d+)\)$", "النطق ({0})"),
    (r"^Voice for (.+)$", "صوت {0}"),
    (r"^reference image (\d+)$", "الصورة المرجعية {0}"),
    (r"^(.+) · Track (\d+)$", "{0} · المقطع {1}"),
    # Timing lines
    (r"^Generation time: (\d+) seconds \(mock\)$", "مدة الإنشاء: {0} ث (تجريبي)"),
    (r"^Generation time: (\d+) seconds$", "مدة الإنشاء: {0} ث"),
    (r"^Extension time: (\d+) seconds$", "مدة التمديد: {0} ث"),
    # Info dialogs ("Current settings")
    (r"^Prompt: (.*)$", "الوصف: {0}"),
    (r"^Negative Prompt: (.*)$", "الوصف السلبي: {0}"),
    (r"^Model: (.*)$", "النموذج: {0}"),
    (r"^Mode: (.*)$", "الوضع: {0}"),
    (r"^Duration: ([\d.]+)s$", "المدة: {0} ث"),
    (r"^Input Image: (.*)$", "الصورة المُدخلة: {0}"),
    (r"^First Frame: (.*)$", "الإطار الأول: {0}"),
    (r"^Last Frame: (.*)$", "الإطار الأخير: {0}"),
    (r"^Asset Images: (\d+) selected$", "الصور المرجعية: {0} مختارة"),
    (r"^Style Image: (.*)$", "صورة الأسلوب: {0}"),
    (r"^Input Video: (.*)$", "الفيديو المُدخل: {0}"),
    (r"^Resolution: (.+)$", "الدقة: {0}"),
    # Music metrics
    (r"^Tempo: ([\d.]+) BPM$", "الإيقاع: {0} نبضة/دقيقة"),
    (r"^Mean Pitch: ([\d.]+) Hz$", "متوسط طبقة الصوت: {0} هرتز"),
    (r"^Pitch Range: ([\d.]+) Hz$", "مدى طبقة الصوت: {0} هرتز"),
    # Errors with a detail appended
    (r"^Couldn't enhance the prompt\. (.*)$", "تعذّر تحسين الوصف. {0}"),
    (r"^Couldn't enhance the script\. (.*)$", "تعذّر تحسين النص. {0}"),
    (r"^Couldn't prepare the video upload\. (.*)$", "تعذّر تجهيز رفع الفيديو. {0}"),
    (r"^Failed to upload image: (.*)$", "تعذّر رفع الصورة: {0}"),
    (r"^Video upload failed: (.*)$", "تعذّر رفع الفيديو: {0}"),
    (
        r"^You can upload a maximum of (\d+) images\. Some files were not uploaded\.$",
        "يمكنك رفع {0} صور كحد أقصى. لم تُرفع بعض الملفات.",
    ),
    (r"^You can upload a maximum of (\d+) images\.$", "يمكنك رفع {0} صور كحد أقصى."),
    (
        r"^You can upload a maximum of (\d+) asset images\.$",
        "يمكنك رفع {0} صور مرجعية كحد أقصى.",
    ),
    (r"^Failed to get suggestions: (.*)$", "تعذّر الحصول على الاقتراحات: {0}"),
    (r"^An error occurred: (.*)$", "حدث خطأ: {0}"),
    (r"^Analysis failed: (.*)$", "تعذّر التحليل: {0}"),
    (r"^Failed to convert to GIF: (.*)$", "تعذّر التحويل إلى GIF: {0}"),
    (
        r"^Error: Could not display analysis data \((.*)\)\.$",
        "خطأ: تعذّر عرض بيانات التحليل ({0}).",
    ),
    (r"^Unknown action: (.*)$", "إجراء غير معروف: {0}"),
]
