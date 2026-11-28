"""Testes da sonda de bancada com respostas HTTP simuladas."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import httpx

import testar_profile2_psn as probe


class Profile2Test(unittest.IsolatedAsyncioTestCase):
    async def test_compara_rotas_e_emite_apenas_mudancas(self):
        chamadas = []
        async_client = httpx.AsyncClient
        sentinela = "CREDENCIAL_SIMULADA"

        def responder(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "us-prof.np.community.playstation.net")
            self.assertEqual(request.url.params["fields"], probe.FIELDS)
            self.assertEqual(request.headers["authorization"], f"Bearer {sentinela}")
            alvo = request.url.path.split("/")[-2]
            chamadas.append(alvo)
            return httpx.Response(200, json={"profile": {
                "onlineId": "ContaTeste",
                "primaryOnlineStatus": "offline" if alvo == "me" else "online",
                "presences": [{"npTitleId": "CUSA05904_00", "titleName": sentinela}],
            }})

        def criar_client(**kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            return async_client(transport=httpx.MockTransport(responder), **kwargs)

        saida = io.StringIO()
        with (patch.object(probe.httpx, "AsyncClient", side_effect=criar_client),
              patch.object(probe, "INTERVALO", 1),
              patch.object(probe, "DURACAO", 2),
              contextlib.redirect_stdout(saida)):
            self.assertEqual(await probe.monitorar(sentinela, "ContaTeste"), 0)

        self.assertEqual(chamadas, ["me", "ContaTeste"] * 2)
        self.assertEqual(len(saida.getvalue().splitlines()), 1)
        self.assertNotIn(sentinela, saida.getvalue())
        estado = json.loads(saida.getvalue())
        self.assertEqual(estado["me"]["status_primario"], "offline")
        self.assertEqual(estado["online_id_explicito"]["presencas"][0]["title_id"], "CUSA05904_00")

    async def test_erro_http_e_perfil_divergente(self):
        respostas = iter([
            httpx.Response(403, text="CREDENCIAL_SIMULADA"),
            httpx.Response(200, json={"profile": {"onlineId": "OutraConta"}}),
            httpx.Response(200, json={"profile": {"onlineId": "ContaTeste"}}),
        ])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(respostas))) as client:
            self.assertEqual(await probe.consultar(client, "me", "ContaTeste"), {"http": 403})
            self.assertEqual(await probe.consultar(client, "me", "ContaTeste"),
                             {"http": 200, "erro": "perfil divergente ou ausente"})
            self.assertEqual(await probe.consultar(client, "me", "ContaTeste"),
                             {"http": 200, "status_primario": None, "presencas": []})


if __name__ == "__main__":
    unittest.main()
