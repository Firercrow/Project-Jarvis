import winreg

CAMINHOS_REGISTRO = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

def listar_programas_instalados() -> list[dict]:
    programas = []
    nomes_vistos = set()

    for raiz, caminho in CAMINHOS_REGISTRO:
        try:
            chave_pai = winreg.OpenKey(raiz, caminho)
        except FileNotFoundError:
            continue

        for i in range(winreg.QueryInfoKey(chave_pai)[0]):
            try:
                nome_subchave = winreg.EnumKey(chave_pai, i)
                with winreg.OpenKey(chave_pai, nome_subchave) as chave:
                    nome, _ = winreg.QueryValueEx(chave, "DisplayName")

                    try:
                        componente_sistema, _ = winreg.QueryValueEx(chave, "SystemComponent")
                    except FileNotFoundError:
                        componente_sistema = 0
                    if componente_sistema == 1:
                        continue

                    if not nome or nome in nomes_vistos:
                        continue
                    nomes_vistos.add(nome)

                    try:
                        versao, _ = winreg.QueryValueEx(chave, "DisplayVersion")
                    except FileNotFoundError:
                        versao = ""
                    try:
                        editora, _ = winreg.QueryValueEx(chave, "Publisher")
                    except FileNotFoundError:
                        editora = ""
                    try:
                        data_instalacao_bruta, _ = winreg.QueryValueEx(chave, "InstallDate")
                    except FileNotFoundError:
                        data_instalacao_bruta = ""
                    try:
                        caminho_instalacao, _ = winreg.QueryValueEx(chave, "InstallLocation")
                    except FileNotFoundError:
                        caminho_instalacao = ""

                    programas.append({
                        "nome": nome,
                        "versao": versao,
                        "editora": editora,
                        "data_instalacao_bruta": data_instalacao_bruta,  # formato AAAAMMDD do registro
                        "caminho_instalacao": caminho_instalacao,  # nem todo programa preenche esse campo
                    })
            except (FileNotFoundError, OSError):
                continue

        winreg.CloseKey(chave_pai)

    return sorted(programas, key=lambda p: p["nome"].lower())

if __name__ == "__main__":
    programas = listar_programas_instalados()
    print(f"{len(programas)} programas encontrados.\n")
    for p in programas[:20]:
        print(f"  {p['nome']} — versão {p['versao'] or '?'} — {p['editora'] or '?'}")
