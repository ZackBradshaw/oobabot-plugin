import importlib
import logging
import types
import typing

import gradio as gr
import oobabot

import modules

from . import oobabot_constants, oobabot_input_handlers, oobabot_layout, oobabot_worker

# can be set in settings.json with:
#   "oobabot-config_file string": "~/oobabot/config.yml",
#
# todo: verify that API extension is running
# todo: automatically use loaded persona
# todo: get Oobabooga settings dir?

params = {
    "is_tab": True,
    "activate": True,
    "config_file": "oobabot-config.yml",
}

##################################
# so, logging_colors.py, rather than using the logging module's built-in
# formatter, is monkey-patching the logging module's StreamHandler.emit.
# This is a problem for us, because we also use the logging module, but
# don't want ANSI color codes showing up in HTML.  We also don't want
# to break their logging.
#
# So, we're going to save their monkey-patched emit, reload the logging
# module, save off the "real" emit, then re-apply their monkey-patch.
#
# We need to do all this before we create the oobabot_worker, so that
# the logs created during startup are properly formatted.

# save the monkey-patched emit
hacked_emit = logging.StreamHandler.emit

# reload the logging module
importlib.reload(logging)

# create our logger early
oobabot.fancy_logger.init_logging(logging.DEBUG, True)
ooba_logger = oobabot.fancy_logger.get()

# manually apply the "correct" emit to each of the StreamHandlers
# that fancy_logger created
for handler in ooba_logger.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.emit = types.MethodType(logging.StreamHandler.emit, handler)

logging.StreamHandler.emit = hacked_emit

##################################

oobabot_worker = oobabot_worker.OobabotWorker(
    modules.shared.args.api_streaming_port,
    params["config_file"],
)
oobabot_layout = oobabot_layout.OobabotLayout()

##################################
# discord token UI

TOKEN_LEN_CHARS = 72


def token_is_plausible(token: str) -> bool:
    return len(token.strip()) >= TOKEN_LEN_CHARS


def make_link_from_token(
    token: str, fn_calc_invite_url: typing.Optional[callable]
) -> str:
    if not token or not fn_calc_invite_url:
        return "A link will appear here once you have set your Discord token."
    link = fn_calc_invite_url(token)
    return (
        f'<a href="{link}" id="oobabot-invite-link" target="_blank">Click here to <pre>'
        + "invite your bot</pre> to a Discord server</a>."
    )


def update_discord_invite_link(new_token: str, is_token_valid: bool, is_tested: bool):
    new_token = new_token.strip()
    prefix = ""
    if is_tested:
        if is_token_valid:
            prefix = "✔️ Your token is valid.<br><br>"
        else:
            prefix = "❌ Your token is invalid."
    if is_token_valid:
        return prefix + make_link_from_token(
            new_token, oobabot_worker.bot.generate_invite_url
        )
    if new_token:
        return prefix
    return "A link will appear here once you have set your Discord token."


def init_button_enablers(token: str, plausible_token: bool) -> None:
    """
    Sets up handlers which will enable or disable buttons
    based on the state of other inputs.
    """

    # first, set up the initial state of the buttons, when the UI first loads
    def enable_when_token_plausible(component: gr.components.IOComponent) -> None:
        component.attach_load_event(
            lambda: component.update(interactive=plausible_token),
            None,
        )

    enable_when_token_plausible(oobabot_layout.discord_token_save_button)
    enable_when_token_plausible(oobabot_layout.ive_done_all_this_button)
    enable_when_token_plausible(oobabot_layout.start_button)

    # initialize the discord invite link value
    oobabot_layout.discord_invite_link_html.attach_load_event(
        lambda: oobabot_layout.discord_invite_link_html.update(
            # pretend that the token is valid here if it's plausible,
            # but don't show a green check
            value=update_discord_invite_link(
                token,
                token_is_plausible,
                False,
            )
        ),
        None,
    )

    # turn on a handler for the token textbox which will enable
    # the save button only when the entered token looks plausible
    oobabot_layout.discord_token_textbox.change(
        lambda token: oobabot_layout.discord_token_save_button.update(
            interactive=token_is_plausible(token)
        ),
        inputs=[oobabot_layout.discord_token_textbox],
        outputs=[
            oobabot_layout.discord_token_save_button,
        ],
    )


def init_button_handlers(
    input_handlers: dict[
        gr.components.IOComponent, oobabot_input_handlers.ComponentToSetting
    ],
) -> None:
    """
    Sets handlers that are called when buttons are pressed
    """

    def handle_save_click(*args):
        # we've been passed the value of every input component,
        # so pass each in turn to our input handler

        results = []
        token = None
        is_token_valid = False

        # iterate over args and input_handlers in parallel
        for new_value, handler in zip(args, input_handlers.values()):
            update = handler.update_component_from_event(new_value)
            results.append(update)
            if handler.component == oobabot_layout.discord_token_textbox:
                # we're looking at the new value of the token, validate it
                token = handler.read_from_settings()
                is_token_valid = oobabot_worker.bot.test_discord_token(new_value)

        oobabot_worker.bot.settings.write_to_file(params["config_file"])

        # results has most of our updates, but we also need to provide ones
        # for the discord invite link and the "I've done all this" button
        results.append(
            oobabot_layout.discord_invite_link_html.update(
                value=update_discord_invite_link(token, is_token_valid, True)
            )
        )
        results.append(
            oobabot_layout.ive_done_all_this_button.update(interactive=is_token_valid)
        )

        return tuple(results)

    oobabot_layout.discord_token_save_button.click(
        handle_save_click,
        inputs=[*input_handlers.keys()],
        outputs=[
            *input_handlers.keys(),
            oobabot_layout.discord_invite_link_html,
            oobabot_layout.ive_done_all_this_button,
        ],
    )

    # TODO_ ENABLE
    # TODO_ ENABLE
    # TODO_ ENABLE
    # TODO_ ENABLE
    # TODO_ ENABLE
    # TODO_ ENABLE
    # TODO_ ENABLE
    # oobabot_layout.reload_character_button.click(
    #     input_handlers[oobabot_layout.character_dropdown].update_component_from_event,
    #     inputs=[],
    #     outputs=[oobabot_layout.character_dropdown],
    # )


##################################
# oobabooga <> extension interface


def ui() -> None:
    """
    Creates custom gradio elements when the UI is launched.
    """
    token = oobabot_worker.bot.settings.discord_settings.get_str("discord_token")
    plausible_token = token_is_plausible(token)

    oobabot_layout.layout_ui(
        get_logs=oobabot_worker.get_logs,
        has_plausible_token=plausible_token,
    )

    # create our own handlers for every input event which will map
    # between our settings object and its corresponding UI component
    input_handlers = oobabot_input_handlers.get_all(
        oobabot_layout,
        oobabot_worker.bot.settings,
    )

    # for all input components, add initialization handlers to
    # set their values from what we read from the settings file
    for component_to_setting in input_handlers.values():
        component_to_setting.init_component_from_setting()

    init_button_handlers(input_handlers)
    init_button_enablers(token, plausible_token)


def custom_css() -> str:
    """
    Returns custom CSS to be injected into the UI.
    """
    return oobabot_constants.LOG_CSS

    # CLEAN = 0  # user has no discord token
    # HAS_TOKEN = 1  # user has discord token, but no bot persona
    # STOPPED = 2  # user has discord token and bot persona, but bot is stopped
    # STARTED = 3  # user has discord token and bot persona, and bot is started
    # STOPPING = 4  # user has discord token and bot persona, and bot is stopping


def custom_js() -> str:
    """
    Returns custom JavaScript to be injected into the UI.
    """
    return oobabot_constants.CUSTOM_JS
