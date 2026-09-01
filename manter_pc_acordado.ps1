# Impede o Windows de suspender/hibernar e de desligar a tela ENQUANTO esta janela estiver
# aberta. Ao fechar, tudo volta ao normal sozinho — o Windows restaura o comportamento padrão
# quando o processo que fez o pedido termina.
#
# Criado em 2026-08-29 pra apresentação por acesso remoto: se o PC dorme, a conexão cai no meio
# da demo. Não altera as configurações de energia do sistema de propósito — mudar o plano de
# energia deixaria o PC sem dormir PARA SEMPRE, e alguém teria que lembrar de desfazer depois.
#
# Usa a mesma API que tocador de vídeo usa pra segurar o PC acordado durante um filme
# (SetThreadExecutionState). O pedido fica registrado no Windows e pode ser conferido com
# "powercfg /requests".

$assinatura = @'
[DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

$energia = Add-Type -MemberDefinition $assinatura -Name 'Energia' -Namespace 'Jarvis' -PassThru

# ES_CONTINUOUS (0x80000000): vale até ser desfeito, não é pedido de uma vez só
# ES_SYSTEM_REQUIRED (0x1): não suspender o computador
# ES_DISPLAY_REQUIRED (0x2): não desligar a tela
$ES_CONTINUOUS = [uint32]'0x80000000'
$ES_SYSTEM_REQUIRED = [uint32]'0x00000001'
$ES_DISPLAY_REQUIRED = [uint32]'0x00000002'

$resultado = $energia::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED)

if ($resultado -eq 0) {
    Write-Host ""
    Write-Host "  FALHOU: o Windows recusou o pedido." -ForegroundColor Red
    Write-Host "  O PC pode dormir normalmente. Feche e tente de novo." -ForegroundColor Red
    Write-Host ""
    Read-Host "Pressione Enter para sair"
    exit 1
}

Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "   PC travado acordado." -ForegroundColor Green
Write-Host "   Nao vai suspender nem apagar a tela." -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
Write-Host "   NAO FECHE ESTA JANELA durante a apresentacao."
Write-Host "   Ao fechar, o PC volta a dormir normalmente."
Write-Host ""
Write-Host "   (conferir a qualquer momento: powercfg /requests)"
Write-Host ""

# Segura o processo vivo. O pedido de "ficar acordado" pertence a esta thread: se ela morrer,
# o Windows solta na hora — que e justamente o comportamento desejado ao fechar a janela.
while ($true) {
    Start-Sleep -Seconds 60
}
