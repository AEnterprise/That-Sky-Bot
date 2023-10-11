import asyncio
import inspect
import re
import typing

from discord import Embed, Reaction
from utils import Emoji, Utils, Configuration, Lang
from dataclasses import dataclass

# Option = namedtuple("Option", "emoji text handler args", defaults=(None, None, None, None))


@dataclass
class Option:
    emoji: str = None
    text: str = None
    handler: typing.Callable = None
    args: typing.Union[str, list] = None


def timeout_format(total_seconds: int) -> str:
    seconds = total_seconds % 60
    minutes = int((total_seconds - seconds) / 60)
    output = []
    if minutes:
        output.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if seconds:
        output.append(f"{seconds} second{'s' if seconds > 1 else ''}")
    return ", ".join(output)


async def ask(bot, channel, author, text, options, timeout=60, show_embed=False, delete_after=False, locale="en_US"):
    description = '\n'.join(f"{Emoji.get_chat_emoji(option.emoji)} {option.text or ''}" for option in options)
    embed = Embed(color=0x68a910, description=description)
    message = await channel.send(text, embed=embed if show_embed else None)
    handlers = dict()
    for option in options:
        emoji = Emoji.get_emoji(option.emoji)
        add_attempts = 10
        # try reaction 10x in case it fails to add
        while add_attempts > 0:
            try:
                await message.add_reaction(emoji)
                break
            except Exception as ex:
                add_attempts = add_attempts - 1
        handlers[str(emoji)] = {'handler': option.handler, 'args': option.args}

    def check(reaction: Reaction, user):
        return user == author and str(reaction.emoji) in handlers.keys() and reaction.message.id == message.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=timeout, check=check)
    except asyncio.TimeoutError as ex:
        try:
            if delete_after:
                await message.delete()
            await channel.send(
                Lang.get_locale_string("questions/error_reaction_timeout", locale,
                                       error_emoji=Emoji.get_emoji("WARNING"),
                                       timeout=timeout_format(timeout)),
                delete_after=10 if delete_after else None)
        except Exception as e:
            # ignore all failures at this point
            pass
        raise ex
    else:
        if delete_after:
            await message.delete()
        h = handlers[str(reaction.emoji)]['handler']
        a = handlers[str(reaction.emoji)]['args']
        if h is None:
            return
        if inspect.iscoroutinefunction(h):
            await h(*a) if a is not None else await h()
        else:
            h(*a) if a is not None else h()


async def ask_text(
        bot,
        channel,
        user,
        text,
        validator=None,
        timeout=Configuration.get_var("question_timeout_seconds"),
        confirm=False,
        escape=True,
        delete_after=False,
        locale="en_US"):

    def check(msg):
        return user == msg.author and msg.channel == channel

    ask_again = True

    def confirmed():
        nonlocal ask_again
        ask_again = False

    def clean_text(txt):
        """Remove multiple spaces and multiple newlines from input txt."""
        txt = re.sub(r' +', ' ', txt)
        txt = re.sub(r'\n\s*\n', '\n\n', txt)
        return txt

    my_messages = []

    async def clean_dialog():
        nonlocal delete_after
        nonlocal my_messages
        if delete_after:
            for msg in my_messages:
                try:
                    await msg.delete()
                except Exception as e:
                    pass

    while ask_again:
        message_cleaned = ""
        content = ""
        my_messages.append(await channel.send(text))
        try:
            while True:
                message = await bot.wait_for('message', timeout=timeout, check=check)
                my_messages.append(message)
                if message.content is None or message.content == "":
                    result = Lang.get_locale_string("questions/text_only", locale)
                else:
                    message_cleaned = clean_text(message.content)
                    # escape_markdown may increase the length of the answer. add buffer if length is limited
                    content = Utils.escape_markdown(message_cleaned) if escape else message_cleaned
                    result = validator(content) if validator is not None else True
                if result is True:
                    break
                else:
                    my_messages.append(await channel.send(result))
        except asyncio.TimeoutError as ex:
            await clean_dialog()
            await channel.send(
                # TODO: remove "bug" from lang string. send report cancel language from Bugs.py exception handler
                Lang.get_locale_string("questions/error_reaction_timeout", locale,
                                       error_emoji=Emoji.get_emoji("WARNING"),
                                       timeout=timeout_format(timeout))
            )
            raise ex
        else:
            if confirm:
                ask_again = True
                backticks = "``" if len(message_cleaned.splitlines()) == 1 else "```"
                message = Lang.get_locale_string('questions/confirm_prompt',
                                                 locale,
                                                 backticks=backticks,
                                                 message=message_cleaned)
                await ask(bot, channel, user, message, [
                    Option("YES", handler=confirmed),
                    Option("NO")
                ], delete_after=delete_after)
            else:
                confirmed()

            if ask_again:
                continue
            await clean_dialog()
            return content


async def ask_attachements(
        bot,
        channel,
        user,
        timeout=Configuration.get_var("question_timeout_seconds"),
        max_files=Configuration.get_var('max_attachments'),
        locale="en_US"):

    def check(message):
        return user == message.author and message.channel == channel

    done = False

    def ready():
        nonlocal done
        done = True

    async def restart_attachments():
        nonlocal final_attachments
        final_attachments = []
        await ask(bot, channel, user, Lang.get_locale_string("questions/attachments_restart", locale), [
            Option("YES", Lang.get_locale_string('questions/restart_attachments_yes', locale)),
            Option("NO", Lang.get_locale_string('questions/restart_attachments_no', locale), handler=ready)
        ], show_embed=True)

    while not done:
        ask_again = True
        final_attachments = []
        count = 0

        def confirmed():
            nonlocal ask_again
            ask_again = False

        while ask_again:
            if not final_attachments:
                await channel.send(Lang.get_locale_string("questions/attachment_prompt",
                                                          locale,
                                                          max=max_files))
            elif len(final_attachments) < max_files - 1:
                await channel.send(
                    Lang.get_locale_string("questions/attachment_prompt_continued",
                                           locale,
                                           max=max_files - len(final_attachments)))
            elif len(final_attachments):
                await channel.send(Lang.get_locale_string("questions/attachment_prompt_final", locale))

            done = False

            try:
                while True:
                    message = await bot.wait_for('message', timeout=timeout, check=check)
                    links = Utils.URL_MATCHER.findall(message.content)
                    attachment_links = [str(a.url) for a in message.attachments]
                    if len(links) != 0 or len(message.attachments) != 0:
                        if (len(links) + len(message.attachments)) > max_files:
                            await channel.send(Lang.get_locale_string("questions/attachments_overflow",
                                                                      locale,
                                                                      max=max_files))
                        else:
                            final_attachments += links + attachment_links
                            count += len(links) + len(attachment_links)
                            break
                    else:
                        await channel.send(Lang.get_locale_string("questions/attachment_not_found", locale))
            except asyncio.TimeoutError as ex:
                await channel.send(
                    Lang.get_locale_string("questions/error_reaction_timeout", locale,
                                           error_emoji=Emoji.get_emoji("WARNING"),
                                           timeout=timeout_format(timeout))
                )
                raise ex
            else:
                if count < max_files:
                    await ask(bot, channel, user, Lang.get_locale_string('questions/another_attachment', locale),
                              [Option("YES"), Option("NO", handler=confirmed)])
                else:
                    ask_again = False

        prompt_yes = Lang.get_locale_string("questions/approve_attachments", locale)
        if len(final_attachments) == 1:
            prompt_no = Lang.get_locale_string('questions/restart_attachment_singular', locale)
        else:
            prompt_no = Lang.get_locale_string('questions/restart_attachment_plural', locale)
        await ask(bot, channel, user, Lang.get_locale_string('questions/confirm_attachments', locale), [
            Option("YES", prompt_yes, handler=ready),
            Option("NO", prompt_no, handler=restart_attachments)
        ], show_embed=True)

    return final_attachments
