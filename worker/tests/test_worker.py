
import unittest
from unittest.mock import Mock, patch

from worker import main


class TestWorker(unittest.TestCase):

    @patch("worker.main.requests.post")
    def test_inferencia_com_sucesso(self, mock_post):
        resposta = Mock()
        resposta.json.return_value = {
            "sentimento": "positivo",
            "confianca": 0.95
        }
        mock_post.return_value = resposta

        resultado = main.executar_inferencia(
            "Gostei muito deste produto"
        )

        self.assertEqual(
            resultado["sentimento"], "positivo"
        )
        mock_post.assert_called_once()

    @patch("worker.main.fila.guardar_status")
    @patch("worker.main.processar_tarefa")
    def test_tarefa_concluida(
        self, mock_processar, mock_status
    ):
        mock_processar.return_value = {
            "sentimento": "positivo",
            "confianca": 0.95
        }

        tarefa = {
            "id": "teste-123",
            "texto": "Gostei muito"
        }

        main.tratar_tarefa(tarefa)

        self.assertEqual(
            mock_status.call_args.args[1]["status"],
            "concluido"
        )

    @patch("worker.main.time.sleep")
    @patch("worker.main.executar_inferencia")
    def test_retenta_tres_vezes(
        self, mock_inferencia, mock_sleep
    ):
        from requests.exceptions import ConnectionError

        mock_inferencia.side_effect = ConnectionError(
            "Servico indisponivel"
        )

        tarefa = {
            "id": "teste-123",
            "texto": "Texto de teste"
        }

        with self.assertRaises(ConnectionError):
            main.processar_tarefa(tarefa)

        self.assertEqual(mock_inferencia.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("worker.main.fila.guardar_status")
    @patch("worker.main.fila.enviar_para_descarte")
    @patch("worker.main.processar_tarefa")
    def test_tarefa_falha_vai_para_descarte(
        self, mock_processar, mock_descarte, mock_status
    ):
        mock_processar.side_effect = Exception(
            "Erro no processamento"
        )

        tarefa = {
            "id": "teste-456",
            "texto": "Texto de teste"
        }

        main.tratar_tarefa(tarefa)

        mock_descarte.assert_called_once()
        self.assertEqual(
            mock_status.call_args.args[1]["status"],
            "falhou"
        )


if __name__ == "__main__":
    unittest.main()
