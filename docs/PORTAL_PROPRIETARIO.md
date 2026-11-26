# Portal do proprietário

Antes de iniciar a aplicação com esta versão, aplique a migração `015_proprietarios.sql` usando `python -m app.migrate` a partir de `backend`.

O superadmin concede o papel `owner` em **Usuários e permissões**. Quem recebe o papel precisa confirmar o e-mail e aceitar a versão vigente dos termos em **Portal do proprietário**. É possível manter o papel de locatário. A API impede que a mesma conta acumule um papel de equipe e o papel de proprietário.

| Endpoint | Operação |
|---|---|
| `GET /owner/terms` | Retorna ID, versão, título, texto e data do aceite vigente, quando houver. |
| `POST /owner/enrollment` | Recebe `policy_version_id` e `accepted: true`. Aceites repetidos da mesma versão são idempotentes. Uma versão substituída retorna `409`. |
| `GET /owner/psn-accounts` | Lista metadados das contas PSN do titular após o aceite. |
| `GET /owner/consoles` | Lista consoles do titular e a situação de publicação após o aceite. |
| `POST /admin/consoles/{id}/diagnostics/run-all` | Executa os diagnósticos em sequência na requisição e devolve os resultados. Aceita `code` para o pareamento manual quando aplicável. |

A migração registra os termos em `policy_documents`, usa `policy_acceptances` para o aceite individual e acrescenta `owner_user_id` ao inventário de consoles e contas PSN. O portal oferece consulta desses recursos. A vinculação pela interface faz parte da etapa posterior de cadastro de inventário.
