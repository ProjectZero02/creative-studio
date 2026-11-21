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
"""Invisible element that turns a NotifyState change into a browser
notification (see common/notify.py)."""

import mesop as me


@me.web_component(path="./notify.js")
def notify_bridge(*, seq: int, title: str, body: str, key: str | None = None):
    return me.insert_web_component(
        key=key,
        name="gm-notify",
        properties={"seq": seq, "title": title, "body": body},
    )
