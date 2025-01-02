import asyncio
import os
import sys
import time
import traceback
from asyncio import CancelledError
from io import BytesIO
from typing import Union
from zipfile import ZipFile, ZIP_DEFLATED

import discord
from discord import Forbidden, File, Interaction, app_commands, User
from discord.ext import commands
from discord.ext.commands import Context

from cogs.BaseCog import BaseCog
from utils import Lang, Questions, Utils, Logging
from utils.Constants import MENTION_MATCHER, ID_MATCHER, NUMBER_MATCHER
from utils.Helper import ConfirmView, Sender
from utils.Logging import TCol
from utils.Utils import interaction_response

try:
    pwd = os.path.dirname(os.path.realpath(__file__))
    music_maker_path = os.path.normpath(os.path.join(pwd, '../sky-python-music-sheet-maker'))
    if not os.path.isdir(music_maker_path):
        music_maker_path = os.path.normpath(os.path.join(pwd, '../../sky-python-music-sheet-maker'))
    if music_maker_path not in sys.path:
        sys.path.append(music_maker_path)
    # Logging.info(sys.path)
    from src.skymusic.communicator import Communicator, QueriesExecutionAbort
    from src.skymusic.music_sheet_maker import MusicSheetMaker
    from src.skymusic.resources import Resources as skymusic_resources
except ImportError as e:
    Logging.info(f"*** IMPORT ERROR of one or several Music-Maker modules: {e}")


async def can_admin(ctx: Context):
    return (await Utils.permission_manage_bot(ctx) or
            (ctx.guild and ctx.author.guild_permissions.manage_channels))


class MusicCogPlayer:

    def __init__(self, cog, locale='en_US'):
        self.cog = cog
        self.name = skymusic_resources.MUSIC_COG_NAME  # Must be defined before instantiating communicator
        self.locale = locale
        self.communicator = Communicator(owner=self, locale=locale)

    def get_name(self):
        return self.name

    def get_locale(self):
        return self.locale

    def receive(self, *args, **kwargs):
        self.communicator.receive(*args, **kwargs)

    def max_length(self, length):
        def real_check(text):
            if len(text) > length:
                return Lang.get_locale_string("music/text_too_long", self.locale, max=length)
                # TODO: check that this string exists
            return True
        return real_check

    async def async_execute_queries(self, channel, user, queries=None):
        question_timeout = 5 * 60  # TODO: config?

        if queries is None:
            self.communicator.memory.clean()
            queries = self.communicator.recall_unsatisfied(filters=('to_me'))
        else:
            if not isinstance(queries, (list, set)):
                queries = [queries]

        for q in queries:
            reply_valid = False
            while not reply_valid:
                async def answer_number(first_number, i):
                    nonlocal answer_number
                    if isinstance(i, int):
                        answer_number = first_number + i
                    else:
                        answer_number = i

                query_dict = self.communicator.query_to_discord(q)
                options = [Questions.Option("QUESTION_MARK", 'Help', handler=answer_number, args=(None, '?'))]

                if 'options' in query_dict:
                    if 0 < len(query_dict['options']) <= 10:
                        reaction_choices = True
                        question_text = query_dict['question']
                        first_number = query_dict['options'][0]['number']
                        option = [Questions.Option("NUMBER_%d" % i,
                                                   option['text'],
                                                   handler=answer_number,
                                                   args=(first_number, i))
                                  for i, option in enumerate(query_dict['options'])]
                        options = options + option
                    else:
                        reaction_choices = False
                        question_text = query_dict['result']
                else:
                    reaction_choices = False
                    question_text = query_dict['result']

                reply_valid = True  # to be sure to break the loop
                if q.get_expect_reply():
                    await channel.typing()

                    if reaction_choices:

                        await Questions.ask(bot=self.cog.bot, channel=channel, author=user, text=question_text,
                                            options=options, show_embed=True, delete_after=True)
                        answer = answer_number

                    else:

                        answer = await Questions.ask_text(self.cog.bot, channel, user,
                                                          question_text, timeout=question_timeout,
                                                          validator=self.max_length(2000))
                    if answer is not None:
                        q.reply_to(answer)
                        reply_valid = q.get_reply_validity()
                    # TODO: handle abort signals

                else:
                    message = await channel.send(question_text)
                    # TODO: add a wait? add something to seperate from next message anyway
                    if message is not None:
                        q.reply_to('ok')
                        reply_valid = q.get_reply_validity()
        return True

    async def send_song_to_channel(self, channel, user, song_bundle, song_title='Untitled'):
        """
        A song bundle is an objcet returning a dictionary of song meta data and a dict of IOString or IOBytes buffers,
        as lists indexed by their RenderMode

        channel:
        user:
        song_bundle:
        song_title:
        """
        await channel.typing()
        message = "Here are your song files(s)"
        song_renders = song_bundle.get_all_renders()

        for render_mode, buffers in song_renders.items():
            my_files = [File(buffer, filename=f"{song_title}_{i:03d}{render_mode.extension}")
                        for (i, buffer) in enumerate(buffers)]

            if len(my_files) < 1:
                channel.send("whoops, no files to send...")
                continue

            if len(my_files) < 4:
                # send images 3 or fewer images to channel
                await channel.send(content=message, files=my_files)
                continue

            # 4+ files get zipped
            try:
                stream = BytesIO()
                zip_file = ZipFile(stream, mode="w", compression=ZIP_DEFLATED)

                with zip_file:
                    # Add sheets to zip file
                    for sheet in my_files:
                        sheet.fp.seek(0)
                        zip_file.writestr(sheet.filename, sheet.fp.getvalue())

                stream.seek(0)
                await channel.send(content="Yo, your music files got zipped",
                                   file=discord.File(stream, f"{song_title}_sheets.zip"))
            except Exception as e:
                await Utils.handle_exception("bad zip!", e)
                await channel.send("oops, zip file borked... contact the authorities!")


async def convert_mention(name):
    out_name = ''
    m = MENTION_MATCHER.match(name)
    n = NUMBER_MATCHER.match(name)
    i = ID_MATCHER.match(name)
    name_id = ''
    if i:
        name_id = i[1]
    elif m:
        name_id = m[2]
    elif n:
        name_id = n[0]
    if name_id:
        try:
            my_user = Utils.BOT.get_user(int(name_id))
            out_name = f"{my_user.display_name}"
        except Exception:
            pass
    out_name = await Utils.clean(name) if not out_name else out_name
    return out_name


class Music(BaseCog):

    def __init__(self, bot):
        bot.music_rendering = False
        super().__init__(bot)
        self.in_progress = dict()  # {user_id: asyncio_task}
        self.is_rendering = None
        m = self.bot.metrics
        m.songs_in_progress.set_function(lambda: len(self.in_progress))
        # TODO: create methods to update the bot metrics and in_progress, etc

    async def cog_load(self):
        Logging.info(f"\t{self.qualified_name}::cog_load")
        # initialize anything that should happen before login
        self.bot.loop.create_task(self.after_ready())
        Logging.info(f"\t{self.qualified_name}::cog_load complete")

    async def after_ready(self):
        Logging.info(f"\t{self.qualified_name}::after_ready waiting...")
        await self.bot.wait_until_ready()
        Logging.info(f"\t{self.qualified_name}::after_ready")

    async def shutdown(self):
        """Called before cog_unload, only when shutting down bot. Custom to this bot."""
        Logging.info(f"{self.qualified_name} shutdown", TCol.Underline, TCol.Header)

    async def cog_unload(self):
        Logging.info("\tCancel bug cleanup tasks...", TCol.Warning)
        cancelling = set(self.in_progress.values())
        Logging.info(cancelling)
        i=1
        for task in cancelling:
            Logging.info(f"\tcanceling {i}...")
            Logging.info(f"\t\ttask {i} is already done? {task.done()}")
            Logging.info(f"\t\ttask {i} is canceled? {task.cancelled()}")
            if not task.done() and not task.cancelled():
                Logging.info(f"task {i} is not done or canceled")
                Logging.info(task)
                task.cancel()
            i += 1
        Logging.info("\tdone queuing cancels...", TCol.Warning)
        if cancelling:
            await asyncio.gather(*cancelling, return_exceptions=True)
        Logging.info("\tdone canceling tasks...", TCol.Warning)
        Logging.info(f"\t{self.qualified_name}::cog_unload")

    async def init_guild(self, guild):
        Logging.info(f"\t{self.qualified_name}::init_guild")

    async def delete_progress(self, user):
        Logging.info(f"\t{self.qualified_name}::delete_progress")
        uid = user.id
        if uid in self.in_progress:
            task = self.in_progress[uid]
            try:
                task.cancel()
            except Exception as e:
                # ignore task cancel failures
                Logging.info(e, exc_info=True)
                pass
            del self.in_progress[uid]
            # if deleted task is recorded as active renderer, remove block
            if self.is_rendering == uid:
                self.is_rendering = None
                self.bot.music_rendering = False

    @commands.command(aliases=['songs'])
    @commands.guild_only()
    @commands.check(can_admin)
    async def songs_in_progress(self, ctx):
        await ctx.send(f"There are  {len(self.in_progress)} songs in progress")

    @app_commands.command(name='song')
    async def app_song(self, interaction: Interaction):
        """Create a Sky music sheet"""
        user = interaction.user

        success_msg = "A new music sheet is now in progress. Check your DMs!"
        if user.id in self.in_progress:
            # ask if user wants to start over
            view = ConfirmView(interaction.user, timeout=10.0)
            question = Lang.get_locale_string("music/start_over", interaction, user=user.mention)
            await interaction_response(interaction).send_message(question, view=view, ephemeral=True)
            await view.wait()

            if view.value is None:
                await interaction.followup.send("You didn't respond in time. Not starting over (head back to DMs!)", ephemeral=True)
                return
            elif view.value:
                await interaction.followup.send(success_msg, ephemeral=True)
                Logging.info(f"\t{self.qualified_name}::app_song deleting progress...")
                await self.delete_progress(user)
            else:
                return  # in-progress song should not be reset. bail out
        else:
            await interaction_response(interaction).send_message(success_msg, ephemeral=True)

        # Start a song creation
        Logging.info(f"\t{self.qualified_name}::app_song starting new actual_transcribe_song", TCol.Header)
        task = self.bot.loop.create_task(self.actual_transcribe_song(user, interaction))
        self.in_progress[user.id] = task
        try:
            await task
        except CancelledError:
            Logging.info("app_song complete (canceled)")
            pass
        else:
            Logging.info("app_song done, no exceptions")

    @commands.max_concurrency(10, wait=False)
    @commands.command(aliases=['song'])
    async def transcribe_song(self, ctx: Context):
        Logging.info(f"\t{self.qualified_name}::transcribe_song", TCol.Header)
        if ctx.guild is not None:
            await ctx.message.delete()  # remove command to not flood chat (unless we are in a DM already)
            # TODO: ask for locale in all available languages
            # TODO: track concurrency?
            #   change wait to True, use on_command so waiting user can be informed of progress?

        user = ctx.author

        if user.id in self.in_progress:
            starting_over = False

            async def start_over():
                nonlocal starting_over
                starting_over = True

            # ask if user wants to start over
            await Questions.ask(bot=self.bot, channel=ctx.channel, author=user,
                                text=Lang.get_locale_string("music/start_over", ctx, user=user.mention),
                                options=[
                                    Questions.Option("YES", Lang.get_locale_string("music/start_over_yes", ctx),
                                                     handler=start_over),
                                    Questions.Option("NO", Lang.get_locale_string("music/start_over_no", ctx))
                                ],
                                show_embed=True, delete_after=True)

            if not starting_over:
                return  # in-progress report should not be reset. bail out

            await self.delete_progress(user)

        # Start a song creation
        Logging.info(f"\t{self.qualified_name}::transcribe_song starting new actual_transcribe_song", TCol.Header)
        task = self.bot.loop.create_task(self.actual_transcribe_song(user, ctx))
        self.in_progress[user.id] = task
        try:
            await task
        except CancelledError as e:
            Logging.info("transcribe_song")
            Logging.info(e, exc_info=True)
            pass

    # @commands.command(aliases=['song'])
    async def actual_transcribe_song(self, user: User, ctx: Union[Context, Interaction]):
        m = self.bot.metrics
        active_question = None
        sender = Sender(ctx)
        cancel = False

        try:
            # starts a dm
            channel = await user.create_dm()
            asking = True
            locale = Lang.get_defaulted_locale(ctx)[0]

            # start global report timer and question timer
            song_start_time = question_start_time = time.time()
            # TODO: m.music_songs_started.inc()

            def update_metrics():
                nonlocal active_question
                nonlocal question_start_time

                now = time.time()
                question_duration = now - question_start_time
                question_start_time = now

                # Record the time taken to answer the previous question
                # TODO: update prom mon with music_ metrics
                # gauge = getattr(m, f"music_question_{active_question}_duration")
                # gauge.set(question_duration)

                active_question = active_question + 1

            if not asking:
                return
            else:

                active_question = 0

                player = MusicCogPlayer(cog=self, locale=locale)
                maker = MusicSheetMaker(locale=locale)

                # 1. Sets Song Parser
                maker.set_song_parser()

                # 2. Displays instructions
                i_instr, _ = maker.ask_instructions(recipient=player, execute=False)
                answered = await player.async_execute_queries(channel, user, i_instr)
                # result = i_instr.get_reply().get_result()
                active_question += 1

                # 3. Asks for notes
                # TODO: allow the player to enter the notes using several messages??? or maybe not
                q_notes, _ = maker.ask_notes(recipient=player, prerequisites=[i_instr], execute=False)
                answered = await player.async_execute_queries(channel, user, q_notes)
                notes = q_notes.get_reply().get_result()
                active_question += 1

                # 4. Asks for input mode (or display the one found)
                q_mode, input_mode = maker.ask_input_mode(recipient=player, notes=notes, prerequisites=[q_notes],
                                                          execute=False)
                answered = await player.async_execute_queries(channel, user, q_mode)
                if input_mode is None:
                    input_mode = q_mode.get_reply().get_result()
                active_question += 1

                # 4b. Sets input_mode
                maker.set_parser_input_mode(recipient=player, input_mode=input_mode)
                active_question += 1

                # 5. Asks for song key (or display the only one possible)
                (q_key, song_key) = maker.ask_song_key(recipient=player, notes=notes, input_mode=input_mode,
                                                       prerequisites=[q_notes, q_mode], execute=False)
                answered = await player.async_execute_queries(channel, user, q_key)
                if song_key is None:
                    song_key = q_key.get_reply().get_result()
                active_question += 1

                # 6. Asks for octave shift
                q_shift, octave_shift = maker.ask_octave_shift(recipient=player, input_mode=input_mode, execute=False)
                answered = await player.async_execute_queries(channel, user, q_shift)
                if octave_shift is None:
                    octave_shift = q_shift.get_reply().get_result()
                active_question += 1

                # 7. Parses song
                maker.parse_song(recipient=player, notes=notes, song_key=song_key, octave_shift=octave_shift)
                active_question += 1

                # 8. Displays error ratio
                i_error, _ = maker.display_error_ratio(recipient=player, prerequisites=[q_notes, q_mode, q_shift],
                                                       execute=False)
                answered = await player.async_execute_queries(channel, user, i_error)
                active_question += 1

                # 9. Asks for song metadata
                qs_meta, _ = maker.ask_song_metadata(recipient=player, execute=False)
                answered = await player.async_execute_queries(channel, user, qs_meta)
                # TODO: convert_mention only converts IDs here, maybe because mentions are escaped before here.
                #  fix or maybe add an unescape or something
                (title, artist, transcript) = [
                    await convert_mention(q.get_reply().get_result()) for q in qs_meta
                ]

                # 9.b Sets song metadata
                maker.set_song_metadata(recipient=player,
                                        meta=(title,
                                              artist,
                                              transcript),
                                        song_key=song_key)
                active_question += 1

                # 10 Asks for render modes
                # q_render, _ = self.ask_render_modes(recipient=recipient)
                # if q_render is not None:
                #     answered = await player.async_execute_queries(channel, user, q_render)
                #     render_modes = q_render.get_reply().get_result()
                # active_question += 1

                # 11 Asks render mode
                q_aspect, aspect_ratio = maker.ask_aspect_ratio(recipient=player, execute=False)
                if aspect_ratio is None:
                    answered = await player.async_execute_queries(channel, user, q_aspect)
                    aspect_ratio = q_aspect.get_reply().get_result()
                active_question += 1

                # 12. Ask beats per minutes
                # q_song_bpm, _ = self.ask_song_bpm(recipient=player, execute=False)
                # EXPERIMENTAL:
                # (q_song_bpm, song_bpm) = self.ask_song_bpm(recipient=recipient, prerequisites=[q_render])
                # if q_song_bpm is not None:
                #     answered = await player.async_execute_queries(channel, user, q_song_bpm)
                #     song_bpm = q_song_bpm.get_reply().get_result()
                # active_question += 1

                while self.bot.music_rendering:
                    # Wait for in-progress renders to finish.
                    await asyncio.sleep(1)

                # Block concurrent renders
                self.bot.music_rendering = True
                self.is_rendering = user.id

                # 13. Renders Song
                song_bundle = await asyncio.get_event_loop().run_in_executor(
                    None,
                    maker.render_song,
                    player,
                    None,
                    aspect_ratio,
                    120)

                # Unblock concurrent renders
                self.bot.music_rendering = False
                self.is_rendering = None

                await player.send_song_to_channel(channel, user, song_bundle, title)
                m.songs_completed.inc()
                active_question += 1
                cancel = True
                Logging.info("actual_transcribe_song done. cancel delete tracker")
        except Forbidden:
            cancel = True
            await sender.send(
                Lang.get_locale_string("music/dm_unable", ctx, user=user.mention),
                delete_after=30, ephemeral=True)
        except asyncio.TimeoutError:
            cancel = True
            await channel.send(Lang.get_locale_string("music/song_timeout", ctx))
        except CancelledError as e:
            Logging.info("actual_transcribe_song canceled")
            await channel.send("`song creation canceled...`")
            raise e
        except Exception as e:
            cancel = True
            await Utils.handle_exception("song creation", e)
        finally:
            if cancel:
                try:
                    del_task = self.bot.loop.create_task(self.delete_progress(user))
                    await del_task
                except CancelledError:
                    # all good
                    pass
                except KeyError:
                    Logging.info(f"song for {user.id} already deleted")
                    pass # can't cancel if it's already canceled


"""
    @commands.command(aliases=['song_tutorial'])
    async def song_tutorial(self, ctx):

        m = self.bot.metrics
        active_question = None
        restarting = False

        # start a dm
        try:
            channel = await ctx.author.create_dm()
            asking = True

            async def abort():
                nonlocal asking
                await ctx.author.send(Lang.get_locale_string("bugs/abort_report", ctx))
                asking = False
                m.reports_abort_count.inc()
                m.reports_exit_question.observe(active_question)
                await self.delete_progress(ctx.author.id)

            # Tutorial code here
"""


async def setup(bot):
    await bot.add_cog(Music(bot))
