"""Pure-Python extraction engine. No external services and no hard-coded contract answers.

Conservative by design: only a clearly signed and effective addendum can
supersede a contract field. Ambiguity is surfaced, never resolved silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Literal


Kind = Literal['contract', 'addendum', 'draft', 'letter', 'unknown']


@dataclass(frozen=True)
class Evidence:
    source_id: str
    filename: str
    paragraph: int  # one-based
    quote: str


@dataclass(frozen=True)
class Condition:
    value: Decimal | date
    evidence: Evidence


@dataclass
class Source:
    source_id: str
    filename: str
    text: str
    paragraphs: list[str]
    kind: Kind
    contract_ids: list[str]
    signed: bool | None = None
    effective_date: date | None = None
    supplier: tuple[str, Evidence] | None = None
    amount: Condition | None = None
    deadline: Condition | None = None
    issues: list[str] = field(default_factory=list)


@dataclass
class Notice:
    source: Source
    reason: str
    proposed_amount: Condition | None
    proposed_deadline: Condition | None


@dataclass
class Contract:
    contract_id: str
    supplier: str | None
    supplier_evidence: Evidence | None
    amount: Condition | None
    deadline: Condition | None
    base_sources: list[Source]
    applied_amendments: list[Source] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)


@dataclass
class Analysis:
    as_of: date
    sources: list[Source]
    contracts: list[Contract]
    unmatched: list[Source]
    global_issues: list[str]


ID = r'[A-Za-zА-Яа-яЁё]{2,12}\s*[-/]\s*\d{2,}(?:[-/]\d{1,4})?'
ID_RE = re.compile(r'(?<!\w)(' + ID + r')(?!\w)', re.I)
CONTRACT_ID_RE = re.compile(
    r'(?:догов[оа]р\w*|контракт\w*)\s*(?:поставки\s*)?(?:№|N\s*|#|номер\s*)?(' + ID + r')', re.I
)
DATE_RE = re.compile(r'(?<!\d)(\d{1,2})[./\-](\d{1,2})[./\-](20\d{2})(?!\d)')
ISO_DATE_RE = re.compile(r'(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)')
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5,
          'июня': 6, 'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10,
          'ноября': 11, 'декабря': 12}
WORDS_DATE_RE = re.compile(r'(?<!\d)(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(20\d{2})(?:\s*года|\s*г\.)?', re.I)
MONEY_RE = re.compile(
    r'(?<![\w\d])((?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[,.]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля|ль)?\b|RUB\b)', re.I
)
SUPPLIER_RE = re.compile(r'(?:поставщик|исполнитель|продавец)\s*[:—–-]\s*([^;\n]+)', re.I)
AMOUNT_HINT = re.compile(r'сумм\w*|цен[ауы]|стоимост\w*|стоимостью|общая\s+сумма', re.I)
DEADLINE_HINT = re.compile(r'поставк\w*|поставить|отгруз\w*|передач\w*\s+(?:товар|продукц)\w*|товар\s+переда', re.I)
DEADLINE_CONTEXT = re.compile(r'срок|до\b|по\b|не\s+позднее|осуществля\w*|планир\w*|назначен\w*', re.I)
BAD_MONEY_CONTEXT = re.compile(r'неустойк|штраф|пен[яи]|аванс|обеспечен\w*|гарантийн\w*', re.I)


def clean_id(raw: str) -> str:
    return re.sub(r'\s+', '', raw).upper()


def split_paragraphs(text: str) -> list[str]:
    """Preserve source substrings; a paragraph is a blank-line-separated block."""
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    return [p.strip() for p in re.split(r'\n[ \t]*\n+', normalized) if p.strip()]


def dates_in(text: str) -> list[tuple[date, int, int]]:
    results: list[tuple[date, int, int]] = []
    for match in DATE_RE.finditer(text):
        try:
            results.append((date(int(match[3]), int(match[2]), int(match[1])), match.start(), match.end()))
        except ValueError:
            pass
    for match in ISO_DATE_RE.finditer(text):
        try:
            results.append((date(int(match[1]), int(match[2]), int(match[3])), match.start(), match.end()))
        except ValueError:
            pass
    for match in WORDS_DATE_RE.finditer(text):
        try:
            results.append((date(int(match[3]), MONTHS[match[2].lower()], int(match[1])), match.start(), match.end()))
        except ValueError:
            pass
    return sorted(set(results), key=lambda x: x[1])


def classify(paragraphs: list[str]) -> Kind:
    header = '\n'.join(paragraphs[:2]).lower()[:750]
    if re.search(r'\bпроект\b|неподписанн\w*\s+проект', header):
        return 'draft'
    if re.search(r'\bписьмо\b|\bобращени[ея]\b|\bуведомлени[ея]\b', header):
        return 'letter'
    if re.search(r'дополнительн\w*\s+соглашени\w*|\bдопсоглашени\w*|соглашени\w*\s+об\s+изменении', header):
        return 'addendum'
    if re.search(r'\bдоговор\b|\bконтракт\b', header):
        return 'contract'
    # Non-template contracts: contract ID, supplier and core business terms in the body.
    joined = '\n'.join(paragraphs)
    if (ID_RE.search(joined) and re.search(r'поставщик\s*[:—–-]', joined, re.I)
            and AMOUNT_HINT.search(joined) and DEADLINE_HINT.search(joined)):
        return 'contract'
    return 'unknown'


def find_contract_ids(paragraphs: list[str]) -> list[str]:
    text = '\n'.join(paragraphs)
    matches = [clean_id(m[1]) for m in CONTRACT_ID_RE.finditer(text)]
    if matches:
        return list(dict.fromkeys(matches))
    # A non-uniform layout may give only 'STN-123' on its own line.
    matches = [clean_id(m[1]) for m in ID_RE.finditer(text)]
    return list(dict.fromkeys(matches))


def ev(source_id: str, filename: str, index: int, para: str) -> Evidence:
    return Evidence(source_id, filename, index + 1, para)


def signed_status(paragraphs: list[str], kind: Kind) -> bool | None:
    if kind != 'addendum':
        return False if kind in ('draft', 'letter') else None
    body = '\n'.join(paragraphs).lower()
    if re.search(r'не\s+подписан|подписи\s+отсутствуют|не\s+согласован|только\s+проект|на\s+согласовани', body):
        return False
    if re.search(r'подписан\w*\s+(?:обеими|двумя)\s+сторон\w*|стороны\s+подписали|подписи\s+обеих\s+сторон\s+имеются', body):
        return True
    # An explicit signature block with filled signatories, not blank template lines.
    signer_roles = re.findall(r'(?:заказчик|покупатель|поставщик|продавец)\s*[:—-]\s*([^\n]+)', body)
    filled = [value for value in signer_roles if re.search(r'подпис\w*\s*[:—-]?\s*[а-яёa-z]{3,}|[а-яёa-z]{3,}\s*\(подписано\)', value)]
    if len(filled) >= 2:
        return True
    return None


def extract_effective(paragraphs: list[str]) -> date | None:
    joined = '\n'.join(paragraphs)
    # First find explicitly stated effective date; never treat a file date as effective.
    for para in paragraphs:
        if re.search(r'вступа\w*\s+в\s+силу|действует\s+с|изменени\w*\s+применя\w*\s+с', para, re.I):
            possible = dates_in(para)
            if len({d for d, _, _ in possible}) == 1:
                return possible[0][0]
    if re.search(r'вступа\w*\s+в\s+силу\s+(?:с\s+момента|со\s+дня)\s+подписан', joined, re.I):
        for para in paragraphs:
            if re.search(r'дат[аы]\s+подписани|подписан\w*\s+\d', para, re.I):
                possible = dates_in(para)
                if len({d for d, _, _ in possible}) == 1:
                    return possible[0][0]
    return None


def extract_supplier(source_id: str, filename: str, paragraphs: list[str]) -> tuple[str, Evidence] | None:
    for ix, para in enumerate(paragraphs):
        match = SUPPLIER_RE.search(para)
        if match:
            name = re.split(r'\s+(?:заказчик|покупатель|сумма|срок)\s*[:—–-]', match[1], flags=re.I)[0].strip(' .')
            if name and not re.fullmatch(r'[_\- ]+', name):
                return name, ev(source_id, filename, ix, para)
    # Handle 'ООО «...» (далее — Поставщик)' with the role after the name.
    for ix, para in enumerate(paragraphs):
        match = re.search(r'(?:ООО|АО|ПАО|ИП)\s*[«\"][^»\"]+[»\"](?=[^\n]{0,80}\bпоставщик\b)', para, re.I)
        if match:
            return match[0], ev(source_id, filename, ix, para)
    return None


def extract_money(source_id: str, filename: str, paragraphs: list[str]) -> tuple[Condition | None, list[str]]:
    candidates: list[Condition] = []
    issues: list[str] = []
    for ix, para in enumerate(paragraphs):
        if not AMOUNT_HINT.search(para) or BAD_MONEY_CONTEXT.search(para):
            continue
        matches = list(MONEY_RE.finditer(para))
        if not matches:
            continue
        try:
            parsed = [(Decimal(m[1].replace(' ', '').replace('\u00a0', '').replace('\u202f', '').replace(',', '.')), m) for m in matches]
        except InvalidOperation:
            continue
        if len(parsed) > 1 and len({p[0] for p in parsed}) > 1:
            if re.search(r'\b(?:с|со)\b.{0,40}\b(?:на|до)\b|новая\s+сумма|изменить\s+сумму\s+на', para, re.I):
                value = parsed[-1][0]
            elif re.search(r'(?:в\s+том\s+числе|в\s+т\.?\s*ч\.?|ндс)', para, re.I):
                value = parsed[0][0]
            else:
                issues.append(f'Неоднозначные суммы в абзаце {ix+1} файла «{filename}».')
                continue
        else:
            value = parsed[0][0]
        candidates.append(Condition(value, ev(source_id, filename, ix, para)))
    if not candidates:
        return None, issues
    if len({c.value for c in candidates}) > 1:
        issues.append(f'Разные суммы в файле «{filename}»; требуется ручная проверка.')
        return None, issues
    return candidates[0], issues


def extract_deadline(source_id: str, filename: str, paragraphs: list[str]) -> tuple[Condition | None, list[str]]:
    candidates: list[Condition] = []
    issues: list[str] = []
    for ix, para in enumerate(paragraphs):
        if not DEADLINE_HINT.search(para) or not DEADLINE_CONTEXT.search(para):
            continue
        possible = dates_in(para)
        if not possible:
            if re.search(r'в\s+течение\s+\d+|после\s+получени', para, re.I):
                issues.append(f'Относительный срок поставки в абзаце {ix+1} файла «{filename}»: нужна проверка.')
            continue
        unique = {d for d, _, _ in possible}
        if len(unique) == 1:
            value = possible[0][0]
        elif re.search(r'(?:срок|дат\w*)\s+поставк\w*.{0,45}\b(?:с|со)\b.{0,45}\bна\b|изменить\s+срок.*\bна\b', para, re.I):
            value = possible[-1][0]
        else:
            # Dates for signature or agreement effectiveness MUST NOT become delivery dates.
            issues.append(f'Несколько возможных дат в абзаце {ix+1} файла «{filename}»: нужна проверка срока.')
            continue
        candidates.append(Condition(value, ev(source_id, filename, ix, para)))
    if not candidates:
        return None, issues
    if len({c.value for c in candidates}) > 1:
        issues.append(f'Разные сроки поставки в файле «{filename}»; требуется ручная проверка.')
        return None, issues
    return candidates[0], issues


def parse_source(filename: str, text: str, index: int) -> Source:
    paragraphs = split_paragraphs(text)
    source_id = f'src-{index}'
    kind = classify(paragraphs)
    amount, amount_issues = extract_money(source_id, filename, paragraphs)
    deadline, date_issues = extract_deadline(source_id, filename, paragraphs)
    source = Source(
        source_id=source_id, filename=filename, text=text, paragraphs=paragraphs,
        kind=kind, contract_ids=find_contract_ids(paragraphs),
        signed=signed_status(paragraphs, kind),
        effective_date=extract_effective(paragraphs) if kind == 'addendum' else None,
        supplier=extract_supplier(source_id, filename, paragraphs) if kind == 'contract' else None,
        amount=amount, deadline=deadline, issues=amount_issues + date_issues,
    )
    if not paragraphs:
        source.issues.append('Файл пуст.')
    if not source.contract_ids:
        source.issues.append('Номер договора не найден в содержимом файла.')
    if kind == 'unknown':
        source.issues.append('Тип документа по содержимому не определен.')
    if kind in ('addendum', 'draft', 'letter') and len(source.contract_ids) > 1:
        source.issues.append('Документ ссылается на несколько договоров: связь требует проверки.')
    return source


def change_intent(source: Source, key: str) -> bool:
    """Detect a possible amendment of a particular field, including split clauses."""
    field_word = r'(?:сумм\w*|цен\w*|стоимост\w*)' if key == 'amount' else r'(?:срок\w*\s+поставк\w*|дат\w*\s+поставк\w*|поставк\w*\s+товар\w*)'
    change_word = r'(?:измен\w*|излож\w*|установ\w*|считать|нов\w*\s+редакц\w*|продл\w*|перенос\w*)'
    # Small window across nearby clauses; a generic agreement title alone is insufficient.
    combined = ' '.join(source.paragraphs)
    return bool(re.search(change_word + r'.{0,150}' + field_word + r'|' + field_word + r'.{0,150}' + change_word, combined, re.I))


def field_changes(source: Source, key: str) -> Condition | None:
    """An amendment updates a field only with a recognisable change clause."""
    condition = getattr(source, key)
    if condition is None:
        return None
    quote = condition.evidence.quote
    # Direct replacement formula is enough; otherwise require explicit field
    # change intent elsewhere in the same document (split-clause documents).
    if re.search(r'измен\w*|установ\w*|излож\w*|нов\w*\s+редакц\w*|составля\w*|определ\w*|считать|продл\w*|перенос\w*', quote, re.I):
        return condition
    if change_intent(source, key):
        return condition
    return None


def analyse(uploaded: list[tuple[str, str]], as_of: date) -> Analysis:
    sources = [parse_source(filename, text, ix + 1) for ix, (filename, text) in enumerate(uploaded)]
    bases: dict[str, list[Source]] = {}
    attached: dict[str, list[Source]] = {}
    unmatched: list[Source] = []
    global_issues: list[str] = []

    for source in sources:
        if source.kind == 'contract' and len(source.contract_ids) == 1:
            bases.setdefault(source.contract_ids[0], []).append(source)
        elif source.kind in ('addendum', 'draft', 'letter') and len(source.contract_ids) == 1:
            attached.setdefault(source.contract_ids[0], []).append(source)
        else:
            unmatched.append(source)

    for contract_id in attached:
        if contract_id not in bases:
            for src in attached[contract_id]:
                unmatched.append(src)
                global_issues.append(f'«{src.filename}» ссылается на {contract_id}, но основной договор не загружен.')

    contracts: list[Contract] = []
    for cid in sorted(bases):
        base_group = bases[cid]
        base = base_group[0]
        obj = Contract(cid, base.supplier[0] if base.supplier else None,
                       base.supplier[1] if base.supplier else None,
                       base.amount, base.deadline, base_group)
        obj.issues.extend(base.issues)
        if len(base_group) > 1:
            obj.issues.append(f'Загружено несколько основных договоров с номером {cid}; приоритет не определён.')
            obj.amount = obj.deadline = None
            obj.supplier = None
            obj.supplier_evidence = None
        if base.amount is None:
            obj.issues.append('Сумма основного договора не найдена или неоднозначна.')
        if base.deadline is None:
            obj.issues.append('Срок поставки основного договора не найден или неоднозначен.')
        if base.supplier is None:
            obj.issues.append('Поставщик не определён по основному договору.')

        modifications: dict[str, list[tuple[date, Source, Condition]]] = {'amount': [], 'deadline': []}
        unresolved_changes: dict[str, list[tuple[date, Source]]] = {'amount': [], 'deadline': []}
        for child in attached.get(cid, []):
            obj.issues.extend(child.issues)
            if child.kind in ('letter', 'draft'):
                obj.notices.append(Notice(child, 'Письмо / неподписанный проект: не изменяет условия договора.', child.amount, child.deadline))
            elif child.signed is not True:
                obj.notices.append(Notice(child, 'Подписи обеих сторон не подтверждены: не применяется.', child.amount, child.deadline))
                obj.issues.append(f'Статус подписания «{child.filename}» не подтвержден.')
            elif child.effective_date is None:
                obj.notices.append(Notice(child, 'Дата вступления в силу не подтверждена: не применяется.', child.amount, child.deadline))
                obj.issues.append(f'Дата вступления в силу «{child.filename}» не подтверждена.')
            elif child.effective_date > as_of:
                obj.notices.append(Notice(child, f'Подписано, но вступает в силу только {child.effective_date:%d.%m.%Y}.', child.amount, child.deadline))
            else:
                obj.applied_amendments.append(child)
                for key in modifications:
                    condition = field_changes(child, key)
                    if condition is not None:
                        modifications[key].append((child.effective_date, child, condition))
                    elif change_intent(child, key):
                        unresolved_changes[key].append((child.effective_date, child))
                if child.amount is None and child.deadline is None:
                    obj.issues.append(f'В «{child.filename}» не распознаны изменяемые условия; проверьте вручную.')
        # Even if amendments exist, unresolved duplicate base contracts aren't overridden.
        if len(base_group) == 1:
            for key, changes in modifications.items():
                unresolved = unresolved_changes[key]
                # A newer amendment that explicitly changes a field but whose
                # value cannot be read invalidates the older known value.
                newest_known = max((d for d, _, _ in changes), default=date.min)
                newest_unresolved = max((d for d, _ in unresolved), default=date.min)
                if newest_unresolved >= newest_known and unresolved:
                    setattr(obj, key, None)
                    obj.issues.append(f'Подписанное изменение поля «{key}» нельзя надежно извлечь; не показываем устаревшее значение.')
                    continue
                if not changes:
                    continue
                newest = max(d for d, _, _ in changes)
                latest = [(src, val) for d, src, val in changes if d == newest]
                if len({val.value for _, val in latest}) > 1:
                    setattr(obj, key, None)
                    obj.issues.append(f'Конфликт подписанных изменений поля «{key}» с одной датой вступления в силу.')
                else:
                    setattr(obj, key, latest[0][1])
        obj.issues = list(dict.fromkeys(obj.issues))
        contracts.append(obj)
    for src in unmatched:
        for issue in src.issues:
            global_issues.append(f'«{src.filename}»: {issue}')
    return Analysis(as_of, sources, contracts, unmatched, list(dict.fromkeys(global_issues)))


def money_text(value: Decimal | None) -> str:
    if value is None:
        return 'нет данных'
    result = f'{value:,.2f}'.replace(',', '\u00a0').replace('.', ',')
    return (result[:-3] if result.endswith(',00') else result) + ' ₽'


def date_text(value: date | None) -> str:
    return value.strftime('%d.%m.%Y') if value else 'нет данных'
