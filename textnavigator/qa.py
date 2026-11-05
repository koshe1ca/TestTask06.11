"""Four assignment questions, computed from Analysis, not memorized from demo files."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from .engine import Analysis, Contract, Evidence, date_text, money_text


@dataclass
class Answer:
    title: str
    text: str
    evidence: list[Evidence]
    caveats: list[str]


def find_contract(analysis: Analysis, contract_id: str) -> Contract | None:
    return next((c for c in analysis.contracts if c.contract_id.casefold() == contract_id.casefold()), None)


def answer_field(analysis: Analysis, contract_id: str, field: str) -> Answer:
    c = find_contract(analysis, contract_id)
    name = 'срок поставки' if field == 'deadline' else 'сумма договора'
    if not c:
        return Answer(f'{contract_id}: {name}', f'Договор {contract_id} не найден среди загруженных основных договоров.', [],
                      ['Загрузите исходный договор; наличие документов, ссылающихся на него, не подтверждает исходные условия.'])
    condition = getattr(c, field)
    if condition is None:
        evidence = []
        # A missing specification can justify "нет данных" with a real quote.
        # This is evidence of absence in the provided source, not a guessed value.
        if field == 'amount':
            for source in c.base_sources:
                for ix, para in enumerate(source.paragraphs):
                    if ('стоимост' in para.lower() and
                            ('спецификац' in para.lower() or 'не указано' in para.lower())):
                        evidence.append(Evidence(source.source_id, source.filename, ix + 1, para))
                        break
        caveats = list(c.issues)
        if evidence:
            caveats.append('Стоимость определена отсутствующей спецификацией; бюджетный лимит не является ценой договора.')
        return Answer(f'{contract_id}: {name}', f'По договору {contract_id} — нет данных ({name}).', evidence, caveats)
    value = date_text(condition.value) if field == 'deadline' else money_text(condition.value)
    applied = next((s for s in c.applied_amendments if s.source_id == condition.evidence.source_id), None)
    origin = f' Условие установлено подписанным допсоглашением «{applied.filename}».' if applied else ' Условие приведено в основном договоре.'
    caveats = list(c.issues)
    if c.notices:
        caveats.append(f'Есть {len(c.notices)} дополнительный(ых) документ(а/ов), который(ые) не меняет(ют) действующие условия.')
    return Answer(f'{contract_id}: {name}', f'{name.capitalize()} по {contract_id} на {date_text(analysis.as_of)}: {value}.{origin}',
                  [condition.evidence], caveats)


def answer_early(analysis: Analysis, cutoff: date = date(2026, 4, 1)) -> Answer:
    early: list[Contract] = []
    missing: list[str] = []
    proposed: list[tuple[Contract, str, list[Evidence]]] = []
    evidence: list[Evidence] = []
    for c in analysis.contracts:
        if c.deadline is None:
            missing.append(c.contract_id)
        elif c.deadline.value < cutoff:
            early.append(c)
            evidence.append(c.deadline.evidence)
        for notice in c.notices:
            if notice.proposed_deadline:
                proposed.append((c, f'{c.contract_id} — предложенный срок {date_text(notice.proposed_deadline.value)}, '
                                 f'документ «{notice.source.filename}» ({notice.reason})', [notice.proposed_deadline.evidence]))
                evidence.append(notice.proposed_deadline.evidence)
    if early:
        first = '; '.join(f'{c.contract_id} — {date_text(c.deadline.value)}' for c in early)
        text = f'По состоянию на {date_text(analysis.as_of)} поставка до {date_text(cutoff)} запланирована по договорам: {first}.'
    else:
        text = f'Среди договоров с подтвержденными датами поставки раньше {date_text(cutoff)} не найдено.'
    if proposed:
        text += '\n\nНе вступившие в силу предложения/изменения срока: ' + '; '.join(p[1] for p in proposed) + '.'
    else:
        text += '\n\nПредложений или изменений срока без подтвержденного вступления в силу не найдено.'
    caveats = []
    if missing:
        caveats.append('Невозможно проверить сроки в договорах без надежно извлеченной даты: ' + ', '.join(missing) + '.')
    caveats.extend(f'{c.contract_id}: ' + issue for c in analysis.contracts for issue in c.issues)
    return Answer('Поставки до 01.04.2026 и несогласованные изменения', text,
                  list({(e.source_id, e.paragraph): e for e in evidence}.values()), caveats)


def preset_answers(analysis: Analysis) -> list[Answer]:
    return [answer_field(analysis, 'STN-101', 'deadline'),
            answer_field(analysis, 'STN-102', 'amount'),
            answer_field(analysis, 'STN-103', 'amount'),
            answer_early(analysis)]
