import tortoise.exceptions
from tortoise.expressions import Q
from tortoise.query_utils import Prefetch

from utils import Database
from utils.Database import *
from tortoise import Tortoise, run_async


async def run():
    await Database.init("test_junk")

    # Need to get a connection. Unless explicitly specified, the name should be 'default'
    conn = Tortoise.get_connection("default")

    tables = {
        "AdminRole",
        "ArtChannel",
        "Attachments",
        "AutoResponder",
        "AutoResponderChannel",
        "AutoResponse",
        "BotAdmin",
        "BugReport",
        "BugReportingChannel",
        "BugReportingPlatform",
        "ConfigChannel",
        "CountWord",
        "CustomCommand",
        "DropboxChannel",
        "Guild",
        "KrillByLines",
        "KrillChannel",
        "KrillConfig",
        "Localization",
        "ModRole",
        "OreoLetters",
        "OreoMap",
        "ReactWatch",
        "Repros",
        "TrustedRole",
        "UserPermission",
        "WatchedEmoji"
    }

    # Now we can execute queries in the normal autocommit mode
    drops = [
        "drop table adminrole;",
        # "drop table aerich;",
        "drop table artchannel;",
        "drop table attachments;",
        "drop table autoresponse;",
        "drop table autoresponderchannel;",
        "drop table autoresponder;",
        "drop table botadmin;",
        "drop table bugreportingchannel;",
        "drop table bugreportingplatform;",
        "drop table configchannel;",
        "drop table countword;",
        "drop table customcommand;",
        "drop table dropboxchannel;",
        "drop table krillbylines;",
        "drop table krillchannel;",
        "drop table krillconfig;",
        "drop table localization;",
        "drop table modrole;",
        "drop table oreoletters;",
        "drop table oreomap;",
        "drop table repros;",
        "drop table bugreport;",
        "drop table trustedrole;",
        "drop table userpermission;",
        "drop table guild;",
        "drop table watchedemoji;",
        "drop table reactwatch;"
    ]
    for query in drops:
        try:
            await conn.execute_query(query)
        except Exception as e:
            print(type(e))
            print(e)

    # Generate the schema
    # DO NOT USE THIS EXCEPT TO INIT A NEW INSTALL
    print("generating schema...")
    try:
        await Tortoise.generate_schemas()
    except Exception as e:
        print(e)
        return
    print('[PASS]')

    print("integrity checks...")
    try:
        await Guild.get_or_create(
            serverid=123456789,
            memberrole=1,
            nonmemberrole=2,
            mutedrole=3,
            betarole=4,
            welcomechannelid=11,
            ruleschannelid=12,
            logchannelid=13,
            entrychannelid=14,
            maintenancechannelid=15,
            rulesreactmessageid=21,
            defaultlocale="en_US"
        )
        my_other_guild, created = await Guild.get_or_create(
            serverid=987654321,
            memberrole=7,
            nonmemberrole=8,
            mutedrole=8,
            betarole=10,
            welcomechannelid=22,
            ruleschannelid=33,
            logchannelid=44,
            entrychannelid=55,
            maintenancechannelid=66,
            rulesreactmessageid=888888,
            defaultlocale="en_US"
        )
    except (tortoise.exceptions.IntegrityError, tortoise.exceptions.TransactionManagementError) as e:
        print("-----------fail Guild ----- CANNOT CONTINUE WITHOUT GUILD")
        print(type(e))
        print(e)
        return

    try:
        await Guild.create(
            serverid=123456789,
            memberrole=7,
            nonmemberrole=8,
            mutedrole=8,
            betarole=10,
            welcomechannelid=22,
            ruleschannelid=33,
            logchannelid=44,
            entrychannelid=55,
            maintenancechannelid=66,
            rulesreactmessageid=888888,
            defaultlocale="en_US"
        )
    except tortoise.exceptions.IntegrityError as e:
        print(f"pass Guild: {type(e)}")
    try:
        await Guild.get(serverid=999)
    except tortoise.exceptions.DoesNotExist as e:
        print(f"pass Guild: {type(e)}")
    try:
        await Guild.get(defaultlocale="en_US")
    except tortoise.exceptions.MultipleObjectsReturned as e:
        print(f"pass Guild: {type(e)}")
    try:
        my_guild = await Guild.get(serverid=123456789)
        another_guild = await Guild.filter(serverid=987654321).first()
    except (tortoise.exceptions.MultipleObjectsReturned, tortoise.exceptions.DoesNotExist) as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        raise e
    tables.remove("Guild")

    try:
        await KrillChannel.create(serverid=123456789, channelid=91)
        await KrillChannel.create(serverid=123456789, channelid=92)
        await KrillChannel.create(serverid=123456790, channelid=91)
        await KrillChannel.create(serverid=123456790, channelid=92)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        raise e
    try:
        await KrillChannel.create(serverid=123456790, channelid=92)
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("KrillChannel")

    try:
        krill_config_01 = await KrillConfig.create(
            guild=my_guild,
            return_home_freq=5,
            shadow_roll_freq=6,
            krill_rider_freq=7,
            crab_freq=8,
            allow_text=False)
        krill_config_02 = await KrillConfig.create(
            guild=another_guild,
            return_home_freq=5,
            shadow_roll_freq=6,
            krill_rider_freq=7,
            crab_freq=8,
            allow_text=False)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        raise e
    try:
        await KrillConfig.create(
            guild=my_guild,
            return_home_freq=10,
            shadow_roll_freq=11,
            krill_rider_freq=12,
            crab_freq=13,
            allow_text=True)
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("KrillConfig")

    try:
        await KrillByLines.create(krill_config=krill_config_01, byline="something1", type=1, channelid=1234, locale="en_US")
        await KrillByLines.create(krill_config=krill_config_01, byline="something2", type=1, channelid=1234)
        await KrillByLines.create(krill_config=krill_config_01, byline="something3", type=1, locale="en_US")
        await KrillByLines.create(krill_config=krill_config_01, byline="something1", type=2)
        await KrillByLines.create(krill_config=krill_config_01, byline="something2", type=2)
        await KrillByLines.create(krill_config=krill_config_01, byline="something3", type=2)
        await KrillByLines.create(krill_config=krill_config_02, byline="something1", type=1, channelid=1234, locale="en_US")
        await KrillByLines.create(krill_config=krill_config_02, byline="something2", type=1, channelid=1234)
        await KrillByLines.create(krill_config=krill_config_02, byline="something3", type=1, locale="en_US")
        await KrillByLines.create(krill_config=krill_config_02, byline="something1", type=2)
        await KrillByLines.create(krill_config=krill_config_02, byline="something2", type=2)
        await KrillByLines.create(krill_config=krill_config_02, byline="something3", type=2)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await KrillByLines.create(krill_config=krill_config_01, byline="something1", type=1)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("KrillByLines")

    try:
        my_bug_platform = await BugReportingPlatform.create(guild=my_guild, branch="beta", platform="ios")
        my_bug_platform2 = await BugReportingPlatform.create(guild=my_guild, branch="beta", platform="android")
        my_bug_platform3 = await BugReportingPlatform.create(guild=my_guild, branch="live", platform="ios")
        my_bug_platform4 = await BugReportingPlatform.create(guild=my_guild, branch="live", platform="android")
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        return
    try:
        await BugReportingPlatform.create(guild=my_guild, branch="beta", platform="ios")  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("BugReportingPlatform")

    try:
        await BugReportingChannel.create(guild=my_guild, channelid=123456, platform=my_bug_platform)
        await BugReportingChannel.create(guild=my_guild, channelid=123456, platform=my_bug_platform2)
        await BugReportingChannel.create(guild=my_other_guild, channelid=123456, platform=my_bug_platform)
        await BugReportingChannel.create(guild=my_other_guild, channelid=123456, platform=my_bug_platform2)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await BugReportingChannel.create(guild=my_guild, channelid=123457, platform=my_bug_platform)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("BugReportingChannel")

    try:
        my_bug_report = await BugReport.create(
            reporter=12345,
            message_id=23456,
            attachment_message_id=34567,
            platform="ios",
            platform_version="12345.00.01",
            branch="live",
            app_version="1.0.0",
            app_build="098765",
            title="bug1",
            deviceinfo="stuff",
            steps="1,2,3",
            expected="work",
            actual="no work",
            additional="nothing else",
            reported_at=987654321)
        my_bug_report2 = await BugReport.create(
            reporter=12345,
            message_id=23457,
            attachment_message_id=34568,
            platform="ios",
            platform_version="12345.00.01",
            branch="beta",
            app_version="1.0.0",
            app_build="098765",
            title="bug2",
            deviceinfo="stuff",
            steps="1,2,3",
            expected="work",
            actual="no work",
            additional="nothing else",
            reported_at=987654322)
        await BugReport.create(
            reporter=12346,
            message_id=23458,
            attachment_message_id=34569,
            platform="android",
            platform_version="12345.00.01",
            branch="live",
            app_version="1.0.0",
            app_build="098765",
            title="bug3",
            deviceinfo="stuff",
            steps="1,2,3",
            expected="work",
            actual="no work",
            additional="nothing else",
            reported_at=987654323)
        await BugReport.create(
            reporter=12347,
            message_id=23459,
            attachment_message_id=34570,
            platform="android",
            platform_version="12345.00.01",
            branch="beta",
            app_version="1.0.0",
            app_build="098765",
            title="bug4",
            deviceinfo="stuff",
            steps="1,2,3",
            expected="work",
            actual="no work",
            additional="nothing else",
            reported_at=987654324)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------fail BugReport:\n\t{type(e)}\n\t{e}")
        return
    tables.remove("BugReport")

    try:
        await Attachments.create(url="fake1", report=my_bug_report)
        await Attachments.create(url="fake2", report=my_bug_report)
        await Attachments.create(url="fake3", report=my_bug_report)
        await Attachments.create(url="fake4", report=my_bug_report)
        await Attachments.create(url="fake5", report=my_bug_report2)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await Attachments.create(url="fake5", report=my_bug_report)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("Attachments")

    try:
        await Repros.create(user=1, report=my_bug_report)
        await Repros.create(user=2, report=my_bug_report)
        await Repros.create(user=3, report=my_bug_report)
        await Repros.create(user=4, report=my_bug_report)
        await Repros.create(user=5, report=my_bug_report)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await Repros.create(user=1, report=my_bug_report)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("Repros")

    try:
        await ConfigChannel.create(serverid=234567, configname="a", channelid=1111)
        await ConfigChannel.create(serverid=234567, configname="b", channelid=2222)
        await ConfigChannel.create(serverid=234567, configname="c", channelid=3333)
        await ConfigChannel.create(serverid=234567, configname="d", channelid=1111)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await ConfigChannel.create(serverid=234567, configname="c", channelid=4444)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("ConfigChannel")

    try:
        await CustomCommand.create(serverid=234567, trigger="ccfake", response="9876")
        await CustomCommand.create(serverid=234567, trigger="ccfake2", response="9876")
        await CustomCommand.create(serverid=234568, trigger="ccfake", response="9876")
        await CustomCommand.create(serverid=234568, trigger="ccfake2", response="9876")
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await CustomCommand.create(serverid=234567, trigger="ccfake", response="9876")  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("CustomCommand")

    try:
        my_ar = await AutoResponder.create(serverid=234567, trigger="arfake", response="9876")
        my_ar2 = await AutoResponder.create(serverid=234567, trigger="arfake2", response="9876")
        my_ar3 = await AutoResponder.create(serverid=234568, trigger="arfake3", response="9876")
        await AutoResponder.create(serverid=234568, trigger="arfake4", response="9876")
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        return
    try:
        await AutoResponder.create(serverid=234567, trigger="arfake", response="9876")
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("AutoResponder")

    try:
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar, channelid=12345, type=AutoResponderChannelType.log)
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar, channelid=23456, type=AutoResponderChannelType.log)
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar2, channelid=12345, type=AutoResponderChannelType.listen)
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar2, channelid=23456, type=AutoResponderChannelType.listen)
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar2, channelid=45678, type=AutoResponderChannelType.response)
        await AutoResponderChannel.create(guild=my_guild, autoresponder=my_ar3, channelid=76543, type=AutoResponderChannelType.response)
        # global ignore channel:
        await AutoResponderChannel.create(guild=my_guild, channelid=99099, type=AutoResponderChannelType.ignore)
        await AutoResponderChannel.create(guild=my_guild, channelid=99100, type=AutoResponderChannelType.ignore)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await AutoResponderChannel.get_or_create(autoresponder=my_ar, channelid=12345, type=AutoResponderChannelType.log)
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("AutoResponderChannel")

    try:
        await AutoResponse.create(autoresponder=my_ar, response="a message", type=AutoResponseType.log)
        await AutoResponse.create(autoresponder=my_ar, response="a message", type=AutoResponseType.mod)
        await AutoResponse.create(autoresponder=my_ar, response="a message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar2, response="a message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar2, response="another message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar2, response="more message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar2, response="yes message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar2, response="no message", type=AutoResponseType.reply)
        await AutoResponse.create(autoresponder=my_ar3, response="a message", type=AutoResponseType.log)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await AutoResponse.create(autoresponder=my_ar, response="a message", type=AutoResponseType.log)
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("AutoResponse")

    try:
        await CountWord.create(serverid=234567, word="fake")
        await CountWord.create(serverid=234567, word="fake2")
        await CountWord.create(serverid=234568, word="fake")
        await CountWord.create(serverid=234568, word="fake2")
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await CountWord.create(serverid=234567, word="fake")
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("CountWord")

    try:
        watcher1 = await ReactWatch.create(serverid=234567)
        watcher2 = await ReactWatch.create(serverid=234568)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
        return
    try:
        await ReactWatch.create(serverid=234567)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("ReactWatch")

    try:
        await WatchedEmoji.create(watcher=watcher1, emoji="a", log=True)
        await WatchedEmoji.create(watcher=watcher1, emoji="b", remove=True)
        await WatchedEmoji.create(watcher=watcher1, emoji="c", mute=True)
        await WatchedEmoji.create(watcher=watcher1, emoji="d", log=True, remove=True, mute=True)
        await WatchedEmoji.create(watcher=watcher2, emoji="a", log=True)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await WatchedEmoji.create(watcher=watcher1, emoji="a", log=False, remove=True, mute=True)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("WatchedEmoji")

    try:
        await ArtChannel.create(serverid=234567, listenchannelid=1, collectionchannelid=2, tag="something")
        await ArtChannel.create(serverid=234567, listenchannelid=3, collectionchannelid=2, tag="something")
        await ArtChannel.create(serverid=234567, listenchannelid=1, collectionchannelid=3, tag="something")
        await ArtChannel.create(serverid=234567, listenchannelid=1, collectionchannelid=2, tag="another")
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await ArtChannel.create(serverid=234567, listenchannelid=1, collectionchannelid=2, tag="something")
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("ArtChannel")

    try:
        await DropboxChannel.create(serverid=234567, sourcechannelid=98765)
        await DropboxChannel.create(serverid=234567, sourcechannelid=98766)
        await DropboxChannel.create(serverid=234568, sourcechannelid=98765)
        await DropboxChannel.create(serverid=234568, sourcechannelid=98766)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await DropboxChannel.create(serverid=234567, sourcechannelid=98765)  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("DropboxChannel")

    try:
        await AdminRole.create(guild=my_guild, roleid=98765)
        await AdminRole.create(guild=my_guild, roleid=98764)
        await AdminRole.create(guild=my_guild, roleid=98763)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await AdminRole.create(guild=my_guild, roleid=98763)  # fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("AdminRole")

    try:
        await BotAdmin.create(userid=98765)
        await BotAdmin.create(userid=98764)
        await BotAdmin.create(userid=98763)
    except Exception as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await BotAdmin.create(userid=98765)  # fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("BotAdmin")

    try:
        await ModRole.create(guild=my_guild, roleid=98765)
        await ModRole.create(guild=my_guild, roleid=98764)
        await ModRole.create(guild=my_guild, roleid=98763)
    except Exception as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await ModRole.create(guild=my_guild, roleid=98763)  # fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("ModRole")

    try:
        await TrustedRole.create(guild=my_guild, roleid=98765)
        await TrustedRole.create(guild=my_guild, roleid=98764)
        await TrustedRole.create(guild=my_guild, roleid=98763)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await TrustedRole.create(guild=my_guild, roleid=98763)  # fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("TrustedRole")

    try:
        await Localization.create(guild=my_guild, channelid=98765, locale='en_US')
        await Localization.create(guild=my_guild, channelid=98766, locale='en_US')
        await Localization.create(guild=my_guild, channelid=98767, locale='ja_JP')
        await Localization.create(guild=my_other_guild, channelid=98765, locale='en_US')
        await Localization.create(guild=my_other_guild, channelid=98766, locale='ja_JP')
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await Localization.create(guild=my_guild, channelid=98765, locale='en_US')  # Fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("Localization")

    try:
        oreo_map, created = await OreoMap.get_or_create()
        oreo_map2, created = await OreoMap.get_or_create()
        oreo_map3 = await OreoMap.first()
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        oreo_map = await OreoMap.create()
        oreo_map4 = await OreoMap.first()
        oreo_map, created = await OreoMap.get_or_create()  # Fail
    except (tortoise.exceptions.IntegrityError, tortoise.exceptions.MultipleObjectsReturned) as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("OreoMap")

    try:
        await OreoLetters.create(token='a', token_class=1)
        await OreoLetters.create(token='a', token_class=2)
        await OreoLetters.create(token='a', token_class=3)
        await OreoLetters.create(token='b', token_class=1)
        await OreoLetters.create(token='b', token_class=2)
        await OreoLetters.create(token='b', token_class=3)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await OreoLetters.create(token='a', token_class=1)
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("OreoLetters")

    try:
        await UserPermission.create(
            guild=my_guild, userid=456787654, command="doSomething", allow=False)
        await UserPermission.create(
            guild=my_guild, userid=456787654, command="doSomethingElse", allow=True)
    except tortoise.exceptions.IntegrityError as e:
        print(f"-----------[FAIL] \n\t{type(e)}\n\t{e}")
    try:
        await UserPermission.create(
            guild=my_guild, userid=456787654, command="doSomethingElse", allow=False)  # fail
    except tortoise.exceptions.IntegrityError as e:
        print(f"[PASS] {type(e)} {e}")
    tables.remove("UserPermission")

    print("\n[INTEGRITY CHECKS COMPLETE]\n")

    my_channel = await DropboxChannel.first()
    await my_channel.delete()

    def get_my_guild():
        return my_guild

    print("\nadmin roles")
    for i in await my_guild.admin_roles:
        print(f"\t{i}")
    print("\nmod roles")
    for i in await my_guild.mod_roles:
        print(f"\t{i}")
    print("\ntrusted roles")
    for i in await my_guild.trusted_roles:
        print(f"\t{i}")
    print("\ncommand permissions")
    print("\tcount: " + str(await my_guild.command_permissions.filter().count()))
    for i in await my_guild.command_permissions:
        print("\t\t"+str(type(i)))
        print(f"\t\t{i}")
    print("\tdelete")
    # delete all
    await get_my_guild().command_permissions.filter().delete()
    print("\tdeleted?")
    for i in await get_my_guild().command_permissions:
        print(f"\t\t{i}")
    print("\tdone with permission abd role tables")

    things = set()
    for row in await KrillChannel.filter(serverid=123456789):
        things.add(row.channelid)

    if(tables):
        print(f"Not checked: {tables}")
    else:
        print("\n#######################\n# All tables verified #\n#######################\n")

    print("let's try some joins...")

    # Localization.select().join(Guild).where(Guild.serverid == ctx.guild.id)
    for i in await my_guild.locales:
        print(f"\t{i}")

    # Localization.select().join(Guild).where(
    #             (Guild.serverid == ctx.guild.id) &
    #             (Localization.channelid == channel_id))

    # my_guild 98765 en_US
    print("fancy join:")
    thing2 = await Localization.filter(guild__serverid=my_guild.serverid, channelid=98765)
    for i in thing2:
        print(f"\t{i}")

    print("fancy join 2:")
    thing3 = await Localization.filter(Q(guild__serverid=my_guild.serverid) & Q(channelid=98766))
    for i in thing3:
        print(f"\t{i}")

    print("fancy join 3:")
    try:
        thing4 = await WatchedEmoji.filter(watcher__serverid=909090)
        print(f"\twatchedemoji attempted with bad server id: {thing4}")
        await WatchedEmoji.filter(watcher__serverid=909090).delete()  # tortoise.exceptions.OperationalError
    except Exception as e:
        print(f"[PASS] {type(e)} {e}")
    thing5 = await WatchedEmoji.filter(watcher__serverid=234567)
    print(f"\twatchedemoji attempted with good server id: {thing5}")
    for i in thing5:
        print(f"\t\t{i}")

    #         conditions = (
    #             BugReport.branch.in_(br) &
    #             BugReport.platform.in_(pl) &
    #             (BugReport.id >= start) &
    #             (BugReport.id <= (sys.maxsize if end is None else end))
    #         )
    # BugReport.select().where(conditions).order_by(BugReport.id.desc()).limit(abs(start))

    print("\n##############\nPrefetch some stuff:")
    try:
        for row in await BugReportingChannel.all().prefetch_related('guild', 'platform'):
            print(f"Bug Reporting Channel {row.channelid} in {row.guild.serverid} for platform/branch {row.platform.platform}/{row.platform.branch}")

        for row in await BugReportingPlatform.all().prefetch_related("bug_channels"):
            print(f"\t-{row.platform}/{row.branch}-")
            for channel_row in row.bug_channels:
                await channel_row.fetch_related("guild", "platform")
                print(f"\t\t--{channel_row.channelid} in {channel_row.guild.serverid}")
    except Exception:
        print("__**prefetch failed**__")

    print("\nExample filters:")
    # Try commenting out br or pl entries. try different start, end, limit values
    br = []
    br.append('live')
    br.append('beta')
    pl = []
    pl.append('android')
    pl.append('ios')
    start = 1
    end = 100
    limit = 0
    conditions = (Q(branch__in=br) &
                  Q(platform__in=pl) &
                  Q(id__range=[start, end]))  # Q(Q(id__gte=start) & Q(id__lte=end)))

    if limit > 0:
        my_bugs = await BugReport.filter(conditions).order_by('-id').limit(limit)
    else:
        my_bugs = await BugReport.filter(conditions)

    for i in my_bugs:
        print(f"\t{i}")
        for att in await i.attachments:
            print(f"\t\t{att.url}")

    print("\n##############\nget some relations:")
    try:
        for row in await AutoResponder.all():
            print(row)
            log_channels = await row.channels.filter(type=AutoResponderChannelType.log)
            response_channels = await row.channels.filter(type=AutoResponderChannelType.response)
            listen_channels = await row.channels.filter(type=AutoResponderChannelType.listen)
            print(f"\tlog channels:")
            for rel in log_channels:
                print(f"\t\t{rel.channelid}, {rel.type}")
            print(f"\tlisten channels:")
            for rel in listen_channels:
                print(f"\t\t{rel.channelid}, {rel.type}")
            print(f"\tresponse channels:")
            for rel in response_channels:
                print(f"\t\t{rel.channelid}, {rel.type}")
            log_responses = await row.responses.filter(type=AutoResponseType.log)
            mod_responses = await row.responses.filter(type=AutoResponseType.log)
            reply_responses = await row.responses.filter(type=AutoResponseType.reply)
            print(f"\tlog responses:")
            for rel in log_responses:
                print(f"\t\t{rel.response}, {rel.type}")
            print(f"\tmod responses:")
            for rel in mod_responses:
                print(f"\t\t{rel.response}, {rel.type}")
            print(f"\treply responses:")
            for rel in reply_responses:
                print(f"\t\t{rel.response}, {rel.type}")
    except Exception as e:
        print("relations failed\n")
        print(e)

    print("\n##############\nsame relations, but prefetched:")
    try:
        for row in await AutoResponder.all().prefetch_related('channels', 'responses'):
            print('=========')
            print(row)
            for i in row.channels:
                print(f"channel id: {i.channelid} type: {i.type}")
            for i in row.responses:
                print(f"response: {i.response} type: {i.type}")
        for row in await AutoResponder.filter(serverid=234567).order_by('id').prefetch_related(
            Prefetch('channels', queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.log), to_attr='log_channels'),
            Prefetch('channels', queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.response), to_attr='response_channels'),
            Prefetch('channels', queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.listen), to_attr='listen_channels'),
            Prefetch('channels', queryset=AutoResponderChannel.filter(type=AutoResponderChannelType.ignore), to_attr='ignored_channels'),
            Prefetch('responses', queryset=AutoResponse.filter(type=AutoResponseType.log).limit(1), to_attr='log_responses'),
            Prefetch('responses', queryset=AutoResponse.filter(type=AutoResponseType.reply), to_attr='reply_responses'),
            Prefetch('responses', queryset=AutoResponse.filter(type=AutoResponseType.mod).limit(1), to_attr='mod_responses')
        ):
            print('--------')
            print(row)
            print(f"log channels: {[c.channelid for c in row.log_channels]}")
            print(f"response channels: {[c.channelid for c in row.response_channels]}")
            print(f"listen channels: {[c.channelid for c in row.listen_channels]}")
            print(f"log responses: {[r.response for r in row.log_responses]}")
            print(f"reply_responses: {[r.response for r in row.reply_responses]}")
            print(f"mod responses: {[r.response for r in row.mod_responses]}")
    except Exception as e:
        print("relations failed:")
        print(e)
        raise e

    print('\n********************\nAR global ignore channel')
    ar_ignored = await AutoResponderChannel.filter(guild=my_guild, autoresponder=None)
    print(ar_ignored)

    # delete without fetching
    print("\nDelete some things:")
    print(AutoResponder.get(id=2).delete().sql())
    try:
        await my_ar2.delete()
    except Exception as e:
        print(e)
    print(BugReport.get(id=1).delete().sql())
    one_bug = await BugReport.get(id=1).delete()
    print(f"\nThis bug was deleted: {one_bug}")

    # fetch then delete. subsequent operations on relations can succeed still (not in this case because cascade)
    print(BugReport.get(id=2).sql())
    my_bug = await BugReport.get(id=2)
    await my_bug.delete()
    print(f"\nThis bug was fetch and then deleted: {my_bug}")
    for att in await my_bug.attachments:
        print(f"\t\t{att.url}")

    try:
        print("\nrelation filter delete")
        # two ways to delete
        await my_guild.bug_channels.filter().delete()
        for row in await my_other_guild.bug_channels:
            print(f"\t\tdelete row? {row.id}")
            await row.delete()
    except Exception:
        print("relation filter delete fail")

if __name__ == "__main__":
    run_async(run())
    print("\nDone!")
