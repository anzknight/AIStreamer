import random
from dataclasses import dataclass
from enum import Enum


class TriggerType(Enum):
    KEYWORD = "keyword"
    EVENT = "event"
    TIMER = "timer"
    CHAT_COUNT = "chat_count"


@dataclass
class Rule:
    name: str
    trigger_type: TriggerType
    trigger_value: str | int
    response_templates: list[str]
    priority: int = 0
    cooldown_seconds: int = 60


class RuleEngine:
    def __init__(self, character: dict):
        self.character = character
        self._cooldowns: dict[str, float] = {}
        self._chat_count: int = 0
        self._rules: list[Rule] = self._build_default_rules()

    def _build_default_rules(self) -> list[Rule]:
        return [
            Rule(
                name="stream_start",
                trigger_type=TriggerType.EVENT,
                trigger_value="stream_start",
                response_templates=[
                    "{name}だよー！今日も配信始めるよ！みんなよろしくね！",
                    "はいはーい！{name}の配信スタート！今日も楽しんでいってね！",
                ],
                priority=10,
                cooldown_seconds=3600,
            ),
            Rule(
                name="game_death",
                trigger_type=TriggerType.EVENT,
                trigger_value="game_death",
                response_templates=[
                    "あーー！やられちゃった！まあ気にしない、次！",
                    "死んだ！笑　でも大丈夫、もう一回！",
                    "うわーまた！くやしいー！絶対リベンジする！",
                ],
                cooldown_seconds=30,
            ),
            Rule(
                name="game_clear",
                trigger_type=TriggerType.EVENT,
                trigger_value="game_clear",
                response_templates=[
                    "やったー！クリアした！めちゃくちゃ嬉しい！！",
                    "やばい！クリアできた！みんなのおかげだよー！",
                ],
                priority=10,
                cooldown_seconds=60,
            ),
            Rule(
                name="chat_milestone_10",
                trigger_type=TriggerType.CHAT_COUNT,
                trigger_value=10,
                response_templates=[
                    "チャットいっぱいありがとう！みんな見てくれてるんだね、嬉しい！",
                ],
                cooldown_seconds=300,
            ),
            Rule(
                name="keyword_kawaii",
                trigger_type=TriggerType.KEYWORD,
                trigger_value="かわいい",
                response_templates=[
                    "えっ、かわいいって言ってくれてありがとう！照れるな〜！",
                    "きゃー！ありがとう！そんなこと言われたら頑張れちゃう！",
                ],
                cooldown_seconds=120,
            ),
            Rule(
                name="keyword_gambare",
                trigger_type=TriggerType.KEYWORD,
                trigger_value="頑張れ",
                response_templates=[
                    "ありがとう！頑張るよー！",
                    "応援してくれてありがとう！絶対頑張る！",
                ],
                cooldown_seconds=60,
            ),
        ]

    def add_rule(self, rule: Rule):
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def check_keyword(self, text: str, current_time: float) -> str | None:
        for rule in self._rules:
            if rule.trigger_type != TriggerType.KEYWORD:
                continue
            if rule.trigger_value.lower() in text.lower():
                if self._check_cooldown(rule.name, current_time, rule.cooldown_seconds):
                    self._cooldowns[rule.name] = current_time
                    template = random.choice(rule.response_templates)
                    return template.format(name=self.character.get("name", "AI"))
        return None

    def check_event(self, event_type: str, current_time: float) -> str | None:
        for rule in self._rules:
            if rule.trigger_type != TriggerType.EVENT:
                continue
            if rule.trigger_value == event_type:
                if self._check_cooldown(rule.name, current_time, rule.cooldown_seconds):
                    self._cooldowns[rule.name] = current_time
                    template = random.choice(rule.response_templates)
                    return template.format(name=self.character.get("name", "AI"))
        return None

    def increment_chat(self, current_time: float) -> str | None:
        self._chat_count += 1
        for rule in self._rules:
            if rule.trigger_type != TriggerType.CHAT_COUNT:
                continue
            if self._chat_count % rule.trigger_value == 0:
                if self._check_cooldown(rule.name, current_time, rule.cooldown_seconds):
                    self._cooldowns[rule.name] = current_time
                    template = random.choice(rule.response_templates)
                    return template.format(name=self.character.get("name", "AI"))
        return None

    def _check_cooldown(self, rule_name: str, current_time: float, cooldown: int) -> bool:
        last = self._cooldowns.get(rule_name, 0)
        return (current_time - last) >= cooldown
