import os
import re
import sys
from datetime import datetime

import typing
from discord import File
from discord.ext import commands
from discord.ext.commands import command
from tortoise.expressions import Q

from cogs.BaseCog import BaseCog
from utils import Utils
from utils.Database import BugReport, BugReportingPlatform
from utils.Utils import save_to_disk


class Reporting(BaseCog):

    fetch_limit = 1000

    async def cog_check(self, ctx):
        return await Utils.can_mod_official(ctx)

    @command(hidden=True)
    async def csv(
            self,
            ctx: commands.Context,
            start: typing.Optional[int] = -100,
            end: typing.Optional[int] = None,
            branch: typing.Optional[str] = "",
            platform: typing.Optional[str] = ""):
        """Export bug reports starting from {start} to CSV file
        csv                      exports 100 most recent reports
        csv 15 20                exports reports with ids in the range 15-20
        csv -200                 exports the last 200 reports matching other criteria (max 1000)
        csv [beta|stable]        exports reports for given branch (all platforms)
        csv {beta|stable} [android|ios|etc]
                                 exports reports for given branch and platform"""
        # TODO: start from date?
        # TODO: migrate to async ORM like tortoise

        async def get_branch(a_branch):
            branches = {p.branch for p in await BugReportingPlatform.all()}

            for this_branch in branches:
                if a_branch.lower() == this_branch.lower():
                    return this_branch

            return branches

        async def get_platform(a_platform):
            platforms = [p.platform for p in await BugReportingPlatform.all()]

            for this_platform in platforms:
                if a_platform.lower() == this_platform.lower():
                    return this_platform

            return platforms

        # dashes at the start of text are interpreted as formulas by excel. replace with *
        def filter_hyphens(text):
            return re.sub(r'^\s*[-=+]\s*', '* ', text, flags=re.MULTILINE)

        pl = await get_platform(platform)
        br = await get_branch(branch)

        if start < -self.fetch_limit:
            await ctx.send(f"you requested more than {self.fetch_limit} records, "
                           f"so I'm only giving you {self.fetch_limit} because I'm a lazy bot")
            start = -self.fetch_limit

        try:
            # send feedback on command. Failure to send should end attempt.
            await ctx.send(
                f"Fetching bug reports...\n"
                f"start id: {start}\n"
                f"end id: {end}\n"
                f"branch: {br}\n"
                f"platform: {pl}\n"
            )
        except Exception as e:
            await Utils.handle_exception("failed to send reporting CSV startup message", e)
            return

        end_id = sys.maxsize if end is None else end
        conditions = (Q(branch__in=br) &
                      Q(platform__in=pl) &
                      Q(id__range=[start, end_id]))

        if start < 0:
            # count backward from end of data. no more than global limit
            limit = min(abs(start), self.fetch_limit)
            query = await BugReport.filter(conditions).order_by("-id").limit(limit)
        else:
            query = await BugReport.filter(conditions).limit(self.fetch_limit)

        data_list = ()
        fields = ["id",
                  "reported_at",
                  "reporter",
                  "platform",
                  "platform_version",
                  "branch",
                  "app_version",
                  "app_build",
                  "title",
                  "deviceinfo",
                  "steps",
                  "expected",
                  "actual",
                  "attachments",
                  "additional"]

        for report in query:
            reporter_formatted = report.reporter
            reporter = self.bot.get_user(report.reporter)
            if reporter is not None:
                reporter_formatted = f"@{reporter.name}#{reporter.discriminator}({report.reporter})"
            attachments = []
            for attachment in await report.attachments:
                attachments.append(attachment.url)

            attachments = "\n".join(attachments)

            data_list += ({"id": report.id,
                           "reported_at": report.reported_at,
                           "reporter": reporter_formatted,
                           "platform": report.platform,
                           "platform_version": report.platform_version,
                           "branch": report.branch,
                           "app_version": report.app_version,
                           "app_build": report.app_build,
                           "title": report.title,
                           "deviceinfo": report.deviceinfo,
                           "steps": filter_hyphens(report.steps),
                           "expected": filter_hyphens(report.expected),
                           "actual": filter_hyphens(report.actual),
                           "attachments": attachments,
                           "additional": filter_hyphens(report.additional)},)

        await ctx.send(f"Fetched {len(data_list)} reports...")
        now = datetime.today().timestamp()
        save_to_disk(f"report_{now}", data_list, 'csv', fields)
        send_file = File(f"report_{now}.csv")
        await ctx.send(file=send_file)
        os.remove(f"report_{now}.csv")


async def setup(bot):
    await bot.add_cog(Reporting(bot))
