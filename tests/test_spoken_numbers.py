"""Valores da Cifra (formato brasileiro) falados certo: 'R$ 7.000,00' é sete mil reais, não sete."""
from cassandra.spoken_numbers import for_speech, number_words
from cassandra.voice import _split_sentences


def test_number_words():
    assert number_words(7000) == "sete mil"
    assert number_words(500) == "quinhentos"
    assert number_words(1500) == "mil e quinhentos"
    assert number_words(2_345_678) == "dois milhões trezentos e quarenta e cinco mil seiscentos e setenta e oito"
    assert number_words(100) == "cem" and number_words(101) == "cento e um"
    assert number_words(21) == "vinte e um"


def test_money_in_brazilian_format():
    assert for_speech("Você gastou R$ 7.000,00 este mês.") == "Você gastou sete mil reais este mês."
    assert for_speech("Sobrou R$ 500,00.") == "Sobrou quinhentos reais."
    assert for_speech("Saldo: R$ 1.234,56") == "Saldo: mil duzentos e trinta e quatro reais e cinquenta e seis centavos"
    assert for_speech("R$ 1,00 e R$ 0,50") == "um real e cinquenta centavos"
    assert for_speech("-R$ 50,00") == "menos cinquenta reais"
    assert for_speech("R$ 2.000.000,00") == "dois milhões de reais"


def test_other_numbers():
    assert for_speech("subiu 12,5% em 2024") == "subiu doze vírgula cinco% em 2024"
    assert for_speech("foram 1.250 compras") == "foram mil duzentos e cinquenta compras"
    assert for_speech("às 14:30, itens 1, 2 e 3") == "às 14:30, itens 1, 2 e 3"


def test_stream_never_splits_inside_a_number():
    sents, rest = _split_sentences("Você gastou R$ 7.")
    assert sents == [] and rest == "Você gastou R$ 7."
    sents, rest = _split_sentences("Você gastou R$ 7.000,00 no mês. Quer")
    assert sents == ["Você gastou R$ 7.000,00 no mês."] and rest == " Quer"
