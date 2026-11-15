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
"""Python API for the <home-prompt> web component (home page hero)."""

import typing

import mesop as me


@me.web_component(path="./home_prompt.js")
def home_prompt(
    *,
    modes: list[dict],
    on_submit: typing.Callable[[me.WebEvent], None] | None = None,
    key: str | None = None,
):
    """One prompt box with a mode switch. Sends {prompt, mode} on submit."""
    return me.insert_web_component(
        key=key,
        name="home-prompt",
        properties={"modes": modes},
        events={"submitEvent": on_submit},
    )
