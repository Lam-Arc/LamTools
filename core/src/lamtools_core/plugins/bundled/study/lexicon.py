"""Bundled Study English→Chinese dictionary.

Three layers answer a lookup, in this order:

``ENTRIES``  the original hand-written lexicon below: concise definitions
             written in-house, kept for the words the Study surfaces rely on.
``TABLE``    ``dictionary/en-zh.jsonl`` — the generated CET-6 table shipped
             with the plugin.  ``scripts/build_study_dictionary.py`` produces
             it; the sibling manifest records the model, counts and hash.
learned      entries a model answer produced at query time, stored in the study
             database so a repeat lookup of the same word never calls a model.

Nothing here copies third-party dictionary text.  Matching resolves ordinary
morphology first (plurals, verb forms, comparatives); a word that no layer
knows is reported as unknown so the caller can fall back to the model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ENTRIES = {
    # Kept from the original hand-written lexicon; these are the words the Study
    # surfaces were designed around and carry verified example sentences.
    'run': ('/rʌn/', 'v.', '跑；运行', 'Move quickly on foot; operate a program.', 'I run every morning.'),
    'study': ('/ˈstʌdi/', 'v. / n.', '学习；研究', 'Spend time learning about a subject.', 'We study mathematics.'),
    'learn': ('/lɜːn/', 'v.', '学习；学会', 'Gain knowledge or a new skill.', ''),
    'knowledge': ('/ˈnɒlɪdʒ/', 'n.', '知识', 'What a person knows or understands.', ''),
    'theorem': ('/ˈθɪərəm/', 'n.', '定理', 'A statement established by a mathematical proof.', ''),
    'function': ('/ˈfʌŋkʃən/', 'n.', '函数；功能', 'A mapping from each input to an output; a purpose.', ''),
    'data': ('/ˈdeɪtə/', 'n.', '数据', 'Values collected for analysis or processing.', ''),
    'model': ('/ˈmɒdl/', 'n.', '模型', 'A simplified representation used to explain or predict.', ''),
    'a': ('/ə/', 'art.', '一个；某个', 'Introduces one unspecified thing.', ''),
    'the': ('/ðə/', 'art.', '这个；那个', 'Points to a particular thing already identifiable.', ''),
    'be': ('/biː/', 'v.', '是；存在', 'Have an identity, state, or existence.', ''),
    'have': ('/hæv/', 'v.', '有；拥有', 'Possess something or experience a state.', ''),
    'do': ('/duː/', 'v.', '做', 'Perform an action or task.', ''),
    'go': ('/ɡəʊ/', 'v.', '去；前往', 'Move toward a place.', ''),
    'come': ('/kʌm/', 'v.', '来', 'Move toward the speaker or a chosen place.', ''),
    'make': ('/meɪk/', 'v.', '制作；使得', 'Create something or bring about a result.', ''),
    'take': ('/teɪk/', 'v.', '拿；采取', 'Get hold of something or choose an action.', ''),
    'give': ('/ɡɪv/', 'v.', '给予', 'Let someone receive something.', ''),
    'get': ('/ɡet/', 'v.', '得到；变得', 'Receive something or enter a new state.', ''),
    'see': ('/siː/', 'v.', '看见；明白', 'Notice with the eyes or understand an idea.', ''),
    'know': ('/nəʊ/', 'v.', '知道', 'Have information or understanding.', ''),
    'think': ('/θɪŋk/', 'v.', '思考；认为', 'Use the mind to form ideas or judgments.', ''),
    'read': ('/riːd/', 'v.', '阅读', 'Understand information expressed in writing.', ''),
    'write': ('/raɪt/', 'v.', '写', 'Express ideas using written symbols.', ''),
    'speak': ('/spiːk/', 'v.', '说；讲话', 'Express words with the voice.', ''),
    'listen': ('/ˈlɪsən/', 'v.', '听', 'Pay attention to sound.', ''),
    'understand': ('/ˌʌndəˈstænd/', 'v.', '理解', 'Grasp what something means or how it works.', ''),
    'explain': ('/ɪkˈspleɪn/', 'v.', '解释', 'Make an idea easier to understand.', ''),
    'ask': ('/ɑːsk/', 'v.', '询问；请求', 'Say a question or make a request.', ''),
    'answer': ('/ˈɑːnsə/', 'n. / v.', '答案；回答', 'A response to a question; to provide that response.', ''),
    'question': ('/ˈkwestʃən/', 'n.', '问题', 'Words used to ask for information.', ''),
    'example': ('/ɪɡˈzɑːmpəl/', 'n.', '例子', 'A particular case that helps explain a general idea.', ''),
    'practice': ('/ˈpræktɪs/', 'n. / v.', '练习；实践', 'Repeated use of a skill to improve it.', ''),
    'test': ('/test/', 'n. / v.', '测试；检验', 'An activity used to check knowledge or behavior.', ''),
    'exam': ('/ɪɡˈzæm/', 'n.', '考试', 'An organized assessment of learning.', ''),
    'result': ('/rɪˈzʌlt/', 'n.', '结果', 'What follows from an action or process.', ''),
    'correct': ('/kəˈrekt/', 'adj. / v.', '正确的；纠正', 'Free from error; to remove an error.', ''),
    'error': ('/ˈerə/', 'n.', '错误', 'A difference from what is correct or intended.', ''),
    'reason': ('/ˈriːzən/', 'n.', '原因；理由', 'An explanation for why something happens or is believed.', ''),
    'evidence': ('/ˈevɪdəns/', 'n.', '证据', 'Information that supports or challenges a claim.', ''),
    'course': ('/kɔːs/', 'n.', '课程', 'An organized series of lessons on a subject.', ''),
    'lesson': ('/ˈlesən/', 'n.', '课；经验', 'A period of teaching or something learned from experience.', ''),
    'subject': ('/ˈsʌbdʒɪkt/', 'n.', '学科；主题', 'An area or topic being studied.', ''),
    'topic': ('/ˈtɒpɪk/', 'n.', '话题；主题', 'The particular matter being discussed.', ''),
    'book': ('/bʊk/', 'n.', '书', 'A collection of written pages or its digital equivalent.', ''),
    'word': ('/wɜːd/', 'n.', '单词；词', 'A unit of language carrying meaning.', ''),
    'sentence': ('/ˈsentəns/', 'n.', '句子', 'A grammatical group of words expressing a thought.', ''),
    'meaning': ('/ˈmiːnɪŋ/', 'n.', '含义', 'The idea communicated by words or signs.', ''),
    'language': ('/ˈlæŋɡwɪdʒ/', 'n.', '语言', 'A shared system for expressing and understanding ideas.', ''),
    'translate': ('/trænzˈleɪt/', 'v.', '翻译', 'Express the meaning of text in another language.', ''),
    'grammar': ('/ˈɡræmə/', 'n.', '语法', 'The patterns used to combine words in a language.', ''),
    'noun': ('/naʊn/', 'n.', '名词', 'A word that names a person, thing, place, or idea.', ''),
    'verb': ('/vɜːb/', 'n.', '动词', 'A word expressing an action or state.', ''),
    'adjective': ('/ˈædʒɪktɪv/', 'n.', '形容词', 'A word describing a noun.', ''),
    'number': ('/ˈnʌmbə/', 'n.', '数；数字', 'A value used to count, measure, or label.', ''),
    'sum': ('/sʌm/', 'n.', '和；总数', 'The value obtained by adding quantities.', ''),
    'difference': ('/ˈdɪfrəns/', 'n.', '差；差异', 'A subtraction result or a way things are unlike.', ''),
    'product': ('/ˈprɒdʌkt/', 'n.', '积；产品', 'A multiplication result or something produced.', ''),
    'fraction': ('/ˈfrækʃən/', 'n.', '分数；部分', 'A quantity written as one number divided by another.', ''),
    'equation': ('/ɪˈkweɪʒən/', 'n.', '方程；等式', 'A statement that two expressions have equal value.', ''),
    'variable': ('/ˈveəriəbəl/', 'n.', '变量', 'A symbol or storage location whose value may change.', ''),
    'constant': ('/ˈkɒnstənt/', 'n. / adj.', '常量；不变的', 'A value kept fixed in a given context.', ''),
    'formula': ('/ˈfɔːmjələ/', 'n.', '公式', 'A symbolic rule connecting quantities.', ''),
    'proof': ('/pruːf/', 'n.', '证明', 'A logical argument establishing a statement.', ''),
    'concept': ('/ˈkɒnsept/', 'n.', '概念', 'An idea used to recognize or reason about something.', ''),
    'method': ('/ˈmeθəd/', 'n.', '方法', 'An organized way to accomplish a task.', ''),
    'vector': ('/ˈvektə/', 'n.', '向量', 'An element of a vector space, often represented by ordered components.', ''),
    'matrix': ('/ˈmeɪtrɪks/', 'n.', '矩阵', 'Numbers or expressions arranged in rows and columns.', ''),
    'gradient': ('/ˈɡreɪdiənt/', 'n.', '梯度', 'The vector of first partial derivatives of a scalar function.', ''),
    'derivative': ('/dɪˈrɪvətɪv/', 'n.', '导数', 'The instantaneous rate at which a function changes.', ''),
    'integral': ('/ˈɪntɪɡrəl/', 'n.', '积分', 'A mathematical accumulation of continuously varying quantities.', ''),
    'limit': ('/ˈlɪmɪt/', 'n.', '极限；限制', 'A value approached by a sequence or function; a boundary.', ''),
    'probability': ('/ˌprɒbəˈbɪləti/', 'n.', '概率', 'A numerical measure of how likely an event is.', ''),
    'random': ('/ˈrændəm/', 'adj.', '随机的', 'Governed by chance rather than a fixed predictable choice.', ''),
    'sample': ('/ˈsɑːmpəl/', 'n.', '样本', 'A selected part used to study a larger group.', ''),
    'mean': ('/miːn/', 'n. / v.', '均值；意指', 'An average value; to express a meaning.', ''),
    'variance': ('/ˈveəriəns/', 'n.', '方差', 'The average squared distance from the mean.', ''),
    'algorithm': ('/ˈælɡərɪðəm/', 'n.', '算法', 'A defined sequence of steps for solving a problem.', ''),
    'structure': ('/ˈstrʌktʃə/', 'n.', '结构', 'The arrangement of parts and their connections.', ''),
    'array': ('/əˈreɪ/', 'n.', '数组', 'A collection whose elements are accessed by index.', ''),
    'list': ('/lɪst/', 'n.', '列表', 'A sequence of items.', ''),
    'tree': ('/triː/', 'n.', '树', 'A branching plant; a connected graph without cycles.', ''),
    'graph': ('/ɡrɑːf/', 'n.', '图；图表', 'Vertices connected by edges; a visual display of values.', ''),
    'node': ('/nəʊd/', 'n.', '节点', 'An individual point or item in a connected structure.', ''),
    'edge': ('/edʒ/', 'n.', '边；连接', 'A boundary or a connection between graph vertices.', ''),
    'network': ('/ˈnetwɜːk/', 'n.', '网络', 'A set of connected elements.', ''),
    'search': ('/sɜːtʃ/', 'v. / n.', '搜索', 'Look through information to find something.', ''),
    'sort': ('/sɔːt/', 'v.', '排序；分类', 'Arrange items according to an order or category.', ''),
    'stack': ('/stæk/', 'n.', '栈', 'A collection where the latest added item is removed first.', ''),
    'queue': ('/kjuː/', 'n.', '队列', 'A collection where the earliest added item is removed first.', ''),
    'memory': ('/ˈmeməri/', 'n.', '记忆；内存', 'The ability or storage used to retain information.', ''),
    'time': ('/taɪm/', 'n.', '时间', 'A measure of when events happen and how long they last.', ''),
    'space': ('/speɪs/', 'n.', '空间', 'Available room, or storage required by a computation.', ''),
    'input': ('/ˈɪnpʊt/', 'n.', '输入', 'Information supplied to a process.', ''),
    'output': ('/ˈaʊtpʊt/', 'n.', '输出', 'Information or a result produced by a process.', ''),
    'value': ('/ˈvæljuː/', 'n.', '值；价值', 'The quantity or content represented by something.', ''),
    'object': ('/ˈɒbdʒɪkt/', 'n.', '对象；物体', 'An identifiable thing; a programming unit with state and behavior.', ''),
    'class': ('/klɑːs/', 'n.', '类；班级', 'A category, a group of learners, or a definition for program objects.', ''),
    'recursion': ('/rɪˈkɜːʒən/', 'n.', '递归', 'Solving a problem by applying the same procedure to smaller instances.', ''),
    'iteration': ('/ˌɪtəˈreɪʃən/', 'n.', '迭代', 'One repetition of a procedure.', ''),
    'complexity': ('/kəmˈpleksəti/', 'n.', '复杂度', 'How resource requirements grow as a problem becomes larger.', ''),
    'science': ('/ˈsaɪəns/', 'n.', '科学', 'Systematic study using evidence and testable explanations.', ''),
    'theory': ('/ˈθɪəri/', 'n.', '理论', 'A connected set of ideas explaining a subject or phenomenon.', ''),
    'hypothesis': ('/haɪˈpɒθəsɪs/', 'n.', '假设', 'A proposed explanation that can be investigated.', ''),
    'experiment': ('/ɪkˈsperɪmənt/', 'n.', '实验', 'A planned observation used to test an idea.', ''),
    'energy': ('/ˈenədʒi/', 'n.', '能量', 'A conserved physical quantity associated with work and change.', ''),
    'force': ('/fɔːs/', 'n.', '力', 'An interaction that can change motion.', ''),
    'mass': ('/mæs/', 'n.', '质量', 'A physical quantity measuring inertia.', ''),
}

_TABLE_PATH = Path(__file__).with_name('dictionary') / 'en-zh.jsonl'
_WORD_RE = re.compile(r"^[a-z][a-z'-]*$")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_IPA_MARKS = 'ˈˌəɪʊɛæʌɒɔɑɜθðʃʒŋɹ'
_IPA_BRACKETS = {'[': ']', '(': ')', '《': '》'}
FORM_KEYS = {'pl', 'pt', 'pp', 'ing', '3sg', 'comparative', 'superlative'}
# Providers and models name the same form differently; map every spelling onto
# the shipped keys so an entry never loses its inflections to a naming choice.
FORM_ALIASES = {
    'plural': 'pl',
    'past': 'pt',
    'past_tense': 'pt',
    'past_participle': 'pp',
    'present_participle': 'ing',
    'gerund': 'ing',
    'present': '3sg',
    'third_person': '3sg',
    'third_person_singular': '3sg',
    '3rd_person_singular': '3sg',
    '3rd_singular': '3sg',
}
IRREGULAR = {
    'ran': 'run', 'running': 'run', 'studies': 'study', 'studied': 'study', 'learnt': 'learn', 'learned': 'learn',
    'went': 'go', 'gone': 'go', 'was': 'be', 'were': 'be', 'is': 'be', 'are': 'be', 'been': 'be', 'has': 'have', 'had': 'have',
    'did': 'do', 'done': 'do', 'made': 'make', 'took': 'take', 'taken': 'take', 'gave': 'give', 'given': 'give',
    'saw': 'see', 'seen': 'see', 'knew': 'know', 'known': 'know', 'thought': 'think', 'wrote': 'write', 'written': 'write',
    'spoke': 'speak', 'spoken': 'speak', 'understood': 'understand', 'matrices': 'matrix', 'hypotheses': 'hypothesis',
}

_TABLE: dict[str, dict] | None = None


def table() -> dict[str, dict]:
    """Return the generated table, parsed once per process.

    A missing or damaged file yields an empty table instead of retrying on
    every lookup: the curated layer and the model fallback still work, and a
    half-written file must not be able to break the Study surface.
    """
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    loaded: dict[str, dict] = {}
    try:
        lines = _TABLE_PATH.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        word = str(entry.get('word') or '')
        if word and word not in loaded:
            loaded[word] = entry
    _TABLE = loaded
    return loaded


def lemmas(text: str) -> list[str]:
    """Candidate headwords for a selection, most specific first."""
    word = text.strip().lower()
    if not _WORD_RE.match(word):
        return []
    candidates = [IRREGULAR.get(word, ''), word]
    if word.endswith('ies'):
        candidates.append(word[:-3] + 'y')
    for suffix in ('ing', 'ed', 'es', 's'):
        if word.endswith(suffix):
            stem = word[:-len(suffix)]
            candidates.extend([stem, stem + 'e', stem[:-1] if len(stem) > 1 and stem[-1] == stem[-2] else ''])
    return [lemma for lemma in dict.fromkeys(candidates) if lemma]


def normalize_phonetic(value: object) -> str:
    """Return a ``/…/`` IPA string, or '' when the value is not usable IPA."""
    text = str(value or '').strip()
    if not text:
        return ''
    if text.startswith('/') and text.endswith('/') and len(text) > 2:
        return text[:60]
    for opening, closing in _IPA_BRACKETS.items():
        if text.startswith(opening) and text.endswith(closing):
            text = text[1:-1].strip()
            break
    # An unwrapped value still counts when it carries IPA marks; a bare word (or
    # a dot-separated respelling) must not be presented as a phonetic.
    if any(mark in text for mark in _IPA_MARKS) or re.search(r'[a-z]+[ˈˌ]', text):
        return f'/{text}/'[:60]
    return ''


def normalize_forms(raw: object) -> dict[str, str]:
    forms: dict[str, str] = {}
    if not isinstance(raw, dict):
        return forms
    for key, value in raw.items():
        key = str(key).strip().lower().replace(' ', '_').strip('_')
        value = str(value or '').strip()
        canonical = key if key in FORM_KEYS else FORM_ALIASES.get(key, '')
        if canonical and value and canonical not in forms:
            forms[canonical] = value[:40]
    return forms


def normalize_entry(raw: object, expected: str | None = None) -> dict | None:
    """Normalize one model-produced entry, or None when it is unusable.

    ``expected`` pins the headword for generated tables; query-time callers pass
    None and accept whatever base form the model returned.
    """
    if not isinstance(raw, dict):
        return None
    word = str(raw.get('word') or '').strip().lower()
    if not _WORD_RE.match(word) or (expected is not None and word != expected):
        return None
    senses = []
    for item in raw.get('senses') or []:
        if not isinstance(item, dict):
            continue
        pos = str(item.get('pos') or '').strip()
        zh = str(item.get('zh') or '').strip()
        en = str(item.get('en') or '').strip()
        if not pos or not zh or not en or not _CJK_RE.search(zh):
            continue
        sense = {'pos': pos[:24], 'zh': zh[:160], 'en': en[:320]}
        example = item.get('example')
        if isinstance(example, dict):
            example_en = str(example.get('en') or '').strip()
            example_zh = str(example.get('zh') or '').strip()
            if example_en and example_zh:
                sense['example'] = {'en': example_en[:240], 'zh': example_zh[:240]}
        senses.append(sense)
    if not senses:
        return None
    entry = {
        'word': word,
        'phonetic_uk': normalize_phonetic(raw.get('phonetic_uk')),
        'phonetic_us': normalize_phonetic(raw.get('phonetic_us')),
        'senses': senses[:3],
    }
    forms = normalize_forms(raw.get('forms'))
    if forms:
        entry['forms'] = forms
    return entry


def curated(word: str, values: tuple[str, str, str, str, str]) -> dict:
    """Present a hand-written tuple as the card contract."""
    phonetic, pos, zh, en, example = values
    sense: dict = {'pos': pos, 'zh': zh, 'en': en}
    if example:
        sense['example'] = {'en': example}
    return {
        'word': word,
        'phonetic': phonetic,
        'phonetic_uk': phonetic,
        'phonetic_us': '',
        'pos': pos,
        'zh': zh,
        'en': en,
        'example': example,
        'senses': [sense],
        'forms': {},
        'source': 'curated',
    }


def lookup(text: str) -> dict | None:
    """Resolve a selection against the layers that ship with the plugin."""
    for lemma in lemmas(text):
        values = ENTRIES.get(lemma)
        if values:
            return curated(lemma, values)
        entry = table().get(lemma)
        if entry:
            return flatten(entry, str(entry.get('source') or 'bundled'))
    return None


def flatten(entry: dict, source: str) -> dict:
    """Present a stored entry as the card contract (flat fields + senses)."""
    senses = [sense for sense in entry.get('senses') or [] if isinstance(sense, dict)]
    first = senses[0] if senses else {}
    example = first.get('example')
    return {
        'word': str(entry.get('word') or ''),
        'phonetic': str(entry.get('phonetic_uk') or entry.get('phonetic_us') or ''),
        'phonetic_uk': str(entry.get('phonetic_uk') or ''),
        'phonetic_us': str(entry.get('phonetic_us') or ''),
        'pos': str(first.get('pos') or ''),
        'zh': str(first.get('zh') or ''),
        'en': str(first.get('en') or ''),
        'example': str((example or {}).get('en') or '') if isinstance(example, dict) else '',
        'senses': senses,
        'forms': entry.get('forms') or {},
        'source': source,
    }
