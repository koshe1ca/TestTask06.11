import unittest
from datetime import date
from decimal import Decimal

from textnavigator.engine import analyse, dates_in, date_text, money_text
from textnavigator.qa import answer_early, answer_field

CHECK = date(2026, 3, 10)


def base(cid='ZK-300', amount='100 000 руб.', deadline='30.03.2026', supplier='ООО «Прайм»'):
    return f'Договор поставки № {cid}\n\nПоставщик: {supplier}\n\nСумма договора: {amount}\n\nСрок поставки — до {deadline}.'


def add(cid='ZK-300', deadline='15.03.2026', effective='09.03.2026', signed=True):
    signed_text = 'Соглашение подписано обеими сторонами.' if signed else 'Документ не подписан.'
    return f'Дополнительное соглашение к договору № {cid}\n\nИзложить условие: срок поставки — не позднее {deadline}.\n\n{signed_text}\n\nСоглашение вступает в силу с {effective}.'


def analysis(*docs):
    return analyse([(f'file{i}.txt', body) for i, body in enumerate(docs)], CHECK)


class EngineTests(unittest.TestCase):
    def test_contract_without_addenda(self):
        c = analysis(base()).contracts[0]
        self.assertEqual(c.contract_id, 'ZK-300')
        self.assertEqual(c.amount.value, Decimal('100000'))
        self.assertEqual(c.deadline.value, date(2026,3,30))
        self.assertEqual(c.amount.evidence.quote, 'Сумма договора: 100 000 руб.')
        self.assertEqual(c.amount.evidence.paragraph, 3)

    def test_signed_effective_addendum_overrides_only_deadline(self):
        c = analysis(base(), add()).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,15))
        self.assertEqual(c.deadline.evidence.filename, 'file1.txt')
        self.assertEqual(c.amount.value, Decimal(100000))
        self.assertEqual(len(c.applied_amendments), 1)

    def test_signed_amendment_updates_amount_too(self):
        amendment = ('Дополнительное соглашение к договору ZK-300\n\n'
                     'Изложить пункт о цене: сумма договора составляет 145 000 рублей.\n\n'
                     'Подписано обеими сторонами.\n\n'
                     'Вступает в силу с 09.03.2026.')
        c = analysis(base(), amendment).contracts[0]
        self.assertEqual(c.amount.value, Decimal(145000))
        self.assertEqual(c.amount.evidence.filename, 'file1.txt')
        self.assertEqual(c.deadline.value, date(2026,3,30))

    def test_signed_but_future_not_applied(self):
        c = analysis(base(), add(effective='11.03.2026')).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,30))
        self.assertEqual(len(c.notices), 1)

    def test_unsigned_addendum_not_applied(self):
        c = analysis(base(), add(signed=False)).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,30))
        self.assertEqual(len(c.notices), 1)

    def test_letter_and_project_not_applied_even_with_dates(self):
        letter = 'ПИСЬМО по договору ZK-300\n\nПредлагаем срок поставки до 01.03.2026.'
        draft = 'ПРОЕКТ допсоглашения к договору ZK-300\n\nНовый срок поставки — до 02.03.2026.'
        c = analysis(base(), letter, draft).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,30))
        self.assertEqual(len(c.notices), 2)
        self.assertEqual(len(c.applied_amendments), 0)

    def test_unknown_effective_date_does_not_override(self):
        no_effective = 'Дополнительное соглашение к договору ZK-300\n\nИзложить срок поставки: до 01.03.2026.\n\nПодписано обеими сторонами.'
        c = analysis(base(), no_effective).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,30))
        self.assertTrue(c.needs_review)

    def test_missing_values_explicitly_empty(self):
        c = analysis('Договор № ZK-300\n\nПоставщик: ООО «Прайм».').contracts[0]
        self.assertIsNone(c.amount)
        self.assertIsNone(c.deadline)
        self.assertIn('нет данных', answer_field(analysis('Договор № ZK-300'), 'ZK-300', 'amount').text)

    def test_filename_irrelevant_to_type_and_priority(self):
        c = analyse([('99_old.txt', base()), ('00_new-contract.txt', add())], CHECK).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,15))

    def test_conflicting_amendments_same_day_do_not_guess(self):
        c = analysis(base(), add(deadline='15.03.2026'), add(deadline='16.03.2026')).contracts[0]
        self.assertIsNone(c.deadline)
        self.assertTrue(any('Конфликт' in issue for issue in c.issues))

    def test_later_effective_amendment_wins_over_upload_order(self):
        c = analysis(base(), add(deadline='17.03.2026', effective='10.03.2026'),
                     add(deadline='15.03.2026', effective='08.03.2026')).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,17))

    def test_relative_deadline_requires_manual_check(self):
        c = analysis(base(deadline='в течение 12 рабочих дней после оплаты')).contracts[0]
        self.assertIsNone(c.deadline)
        self.assertTrue(c.needs_review)

    def test_missing_base_is_unmatched(self):
        a = analysis(add())
        self.assertEqual(len(a.contracts), 0)
        self.assertEqual(len(a.unmatched), 1)

    def test_change_field_in_uploaded_document_affects_result(self):
        original = analysis(base(amount='100 000 руб.')).contracts[0]
        changed = analysis(base(amount='195 000 руб.')).contracts[0]
        self.assertNotEqual(original.amount.value, changed.amount.value)
        self.assertEqual(changed.amount.value, Decimal(195000))

    def test_nonstandard_contract_layout(self):
        doc = 'ZK-987\n\nПоставщик: АО «Новый поставщик»\n\nОбщая стоимость поставки: 570 000 RUB\n\nОтгрузить продукцию до 2026-03-29.'
        a = analysis(doc)
        self.assertEqual(len(a.contracts), 1, 'New contract without standard header must be recognized')
        c = a.contracts[0]
        self.assertEqual(c.amount.value, Decimal(570000))
        self.assertEqual(c.deadline.value, date(2026,3,29))

    def test_unknown_new_signed_deadline_does_not_keep_stale_base(self):
        new = ('Дополнительное соглашение к договору ZK-300\n\n'
               'Изложить срок поставки в следующей редакции.\n\n'
               'Срок поставки — в течение 20 дней после оплаты.\n\n'
               'Подписано обеими сторонами.\n\n'
               'Вступает в силу с 08.03.2026.')
        c = analysis(base(), new).contracts[0]
        self.assertIsNone(c.deadline)
        self.assertTrue(c.needs_review)

    def test_split_amendment_clause_applies_new_date(self):
        new = ('Дополнительное соглашение к договору ZK-300\n\n'
               'Стороны решили изменить срок поставки товара.\n\n'
               'Срок поставки — до 18.03.2026.\n\n'
               'Подписано обеими сторонами.\n\n'
               'Вступает в силу с 08.03.2026.')
        c = analysis(base(), new).contracts[0]
        self.assertEqual(c.deadline.value, date(2026,3,18))

    def test_sums_not_penalties(self):
        doc = base() + '\n\nНеустойка составляет 5 000 руб.'
        self.assertEqual(analysis(doc).contracts[0].amount.value, Decimal(100000))

    def test_no_false_date_from_signature(self):
        doc = base(deadline='25.04.2026') + '\n\nДата подписания: 05.03.2026.'
        self.assertEqual(analysis(doc).contracts[0].deadline.value, date(2026,4,25))

    def test_money_format(self):
        self.assertEqual(money_text(Decimal('780000.50')), '780\u00a0000,50 ₽')

    def test_fourth_question_flags_pending(self):
        c = analysis(base(deadline='30.03.2026'), 'Письмо по договору № ZK-300\n\nПредлагаем срок поставки до 20.04.2026.')
        result = answer_early(c)
        self.assertIn('ZK-300 — 30.03.2026', result.text)
        self.assertIn('20.04.2026', result.text)
        self.assertEqual(len(result.evidence), 2)


if __name__ == '__main__':
    unittest.main()
