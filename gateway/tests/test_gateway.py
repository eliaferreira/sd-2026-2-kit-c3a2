"""
Testes do gateway: saude, roteamento para a inferencia, tratamento de falhas
e privacidade dos logs (LGPD).
"""
import requests

from conftest import RespostaFalsa


def test_saude_retorna_200(client):
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_predict_repassa_texto_para_inferencia(client, auth, inferencia_falsa):
    resposta = client.post("/predict", json={"texto": "servico excelente"}, headers=auth)

    assert resposta.status_code == 200
    assert resposta.json()["sentimento"] == "positivo"

    chamada = inferencia_falsa["chamadas"][0]
    assert chamada["url"].endswith("/predict")
    assert chamada["json"] == {"texto": "servico excelente"}


def test_predict_usa_url_de_variavel_de_ambiente(client, auth, inferencia_falsa):
    client.post("/predict", json={"texto": "ok"}, headers=auth)
    assert inferencia_falsa["chamadas"][0]["url"].startswith("http://inferencia-falsa:8001")


def test_predict_define_tempo_limite_na_chamada(client, auth, inferencia_falsa):
    """Sem timeout, uma inferencia travada prende o gateway para sempre."""
    client.post("/predict", json={"texto": "ok"}, headers=auth)
    timeout = inferencia_falsa["chamadas"][0].get("timeout")
    assert timeout is not None and timeout > 0


def test_predict_inferencia_fora_do_ar_retorna_503(client, auth, inferencia_falsa):
    inferencia_falsa["erro"] = requests.ConnectionError("conexao recusada")
    resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
    assert resposta.status_code == 503


def test_predict_inferencia_lenta_retorna_503(client, auth, inferencia_falsa):
    inferencia_falsa["erro"] = requests.Timeout("tempo esgotado")
    resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
    assert resposta.status_code == 503


def test_predict_inferencia_com_erro_5xx_retorna_503(client, auth, inferencia_falsa):
    inferencia_falsa["resposta"] = RespostaFalsa(500, {"detail": "falhou"})
    resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
    assert resposta.status_code == 503


def test_predict_sem_campo_texto_retorna_422(client, auth, inferencia_falsa):
    resposta = client.post("/predict", json={}, headers=auth)
    assert resposta.status_code == 422
    assert inferencia_falsa["chamadas"] == []


def test_log_nao_expoe_texto_do_usuario(client, auth, inferencia_falsa, capsys):
    """LGPD: o log registra rota/status/latencia, nunca o conteudo enviado."""
    dado_pessoal = "cpf-123.456.789-00"
    client.post("/predict", json={"texto": f"meu cpf e {dado_pessoal}"}, headers=auth)

    saida = capsys.readouterr().out
    assert "/predict" in saida
    assert dado_pessoal not in saida
