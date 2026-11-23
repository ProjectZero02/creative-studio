import mesop as me
import typing

@me.web_component(path="./theme_manager.js")
def theme_manager(
    *,
    theme: str,
    on_theme_load: typing.Callable[[me.WebEvent], None],
    key: str | None = "gm-theme-manager",
):
    return me.insert_web_component(
        key=key,
        name="theme-manager",
        properties={
            "theme": theme,
        },
        events={
            "themeLoaded": on_theme_load,
        },
    )
