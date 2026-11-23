
import json
import unittest
from unittest.mock import Mock, patch

from worker import fila


class TestFila(unittest.TestCase):

    @patch("worker.fila.conectar")
    def test_publicar_tarefa(self, mock_conectar):
        redis_falso = Mock()
        mock_conectar.return_value = redis_falso

        tarefa_id = fila.publicar_tarefa(
            "Gostei muito deste produto"
        )

        redis_falso.rpush.assert_called_once()

        chave, mensagem = redis_falso.rpush.call_args.args
        dados = json.loads(mensagem)

        self.assertEqual(chave, fila.FILA_TAREFAS)
        self.assertEqual(dados["id"], tarefa_id)
        self.assertEqual(
            dados["texto"], "Gostei muito deste produto"
        )

    @patch("worker.fila.conectar")
    def test_consumir_tarefa(self, mock_conectar):
        redis_falso = Mock()
        redis_falso.blpop.return_value = (
            fila.FILA_TAREFAS,
            json.dumps({
                "id": "123",
                "texto": "Texto de teste"
            })
        )
        mock_conectar.return_value = redis_falso

        tarefa = fila.consumir_tarefa(timeout=5)

        self.assertEqual(tarefa["id"], "123")
        self.assertEqual(
            tarefa["texto"], "Texto de teste"
        )

    @patch("worker.fila.conectar")
    def test_consultar_status(self, mock_conectar):
        redis_falso = Mock()
        redis_falso.get.return_value = json.dumps({
            "status": "concluido",
            "resultado": {
                "sentimento": "positivo"
            }
        })
        mock_conectar.return_value = redis_falso

        resultado = fila.consultar_status("123")

        self.assertEqual(
            resultado["status"], "concluido"
        )

    @patch("worker.fila.conectar")
    def test_enviar_para_descarte(self, mock_conectar):
        redis_falso = Mock()
        mock_conectar.return_value = redis_falso

        tarefa = {
            "id": "456",
            "texto": "Texto de teste"
        }

        fila.enviar_para_descarte(
            tarefa,
            "Erro no processamento"
        )

        redis_falso.rpush.assert_called_once()

        chave, mensagem = redis_falso.rpush.call_args.args
        dados = json.loads(mensagem)

        self.assertEqual(chave, fila.FILA_DESCARTE)
        self.assertEqual(
            dados["erro"], "Erro no processamento"
        )


if __name__ == "__main__":
    unittest.main()
