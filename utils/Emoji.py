from discord import utils

from utils import Configuration

EMOJI = dict()

BACKUPS = {
    "ANDROID": "🤖",
    "BETA": "🌙",
    "DEMO": "⚙️",
    "BUG": "🐛",
    "IOS": "🍎",
    "NO": "🚫",
    "STABLE": "🌞",
    "SWITCH": "🍄",
    "PLAYSTATION": "🎮",
    "WINDOWS": "🖥️",
    "WRENCH": "🔧",
    "YES": "✅",
    "CANDLE": "🕯",
    "WARNING": "⚠",
    "WHAT": "☹",
    "ART": "🖼️",
    "BRUSH": "🖌️",
    "LOVE_LETTER": "💌",
    "SCROLL": "📜",
    "SNAIL": "🐌",
    "LEFT": "⬅️",
    "RIGHT": "➡️",
    "NUMBER_0": "0\u20e3",
    "NUMBER_1": "1\u20e3",
    "NUMBER_2": "2\u20e3",
    "NUMBER_3": "3\u20e3",
    "NUMBER_4": "4\u20e3",
    "NUMBER_5": "5\u20e3",
    "NUMBER_6": "6\u20e3",
    "NUMBER_7": "7\u20e3",
    "NUMBER_8": "8\u20e3",
    "NUMBER_9": "9\u20e3",
    "QUESTION_MARK": "❓"
}


def initialize(bot):
    for name, eid in Configuration.get_var("EMOJI", {}).items():
        EMOJI[name] = utils.get(bot.emojis, id=eid)


def get_chat_emoji(name):
    return str(get_emoji(name))


def is_emoji_defined(name):
    if name not in EMOJI and name not in BACKUPS:
        return False
    return True


def get_emoji(name):
    if is_emoji_defined(name):
        if name in EMOJI:
            return EMOJI[name]
        if name in BACKUPS:
            return BACKUPS[name]
    return f"[emoji:{name}]"
