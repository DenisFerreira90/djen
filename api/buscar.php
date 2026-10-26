<?php
/**
 * Consulta pública ao DJEN/CNJ — sem banco de dados e sem credenciais.
 * Exige PHP 7.4+ e acesso HTTPS de saída ao CNJ.
 */
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, private');
header('X-Content-Type-Options: nosniff');

function resposta(int $codigo, array $conteudo): void {
    http_response_code($codigo);
    echo json_encode($conteudo, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    resposta(405, ['ok'=>false,'erro'=>'Utilize uma requisição GET.']);
}

// Somente parâmetros conhecidos chegam ao CNJ; o endereço remoto é fixo (sem SSRF).
$entradas = [
    'numeroOab' => 32, 'ufOab' => 2, 'nomeAdvogado' => 140,
    'numeroProcesso' => 32, 'nomeParte' => 140,
    'siglaTribunal' => 12, 'texto' => 250,
    'dataDisponibilizacaoInicio' => 10,
    'dataDisponibilizacaoFim' => 10, 'meio' => 2
];
$filtros=[];
foreach ($entradas as $campo=>$limite) {
    $valor = $_GET[$campo] ?? '';
    if (!is_string($valor)) resposta(400,['ok'=>false,'erro'=>'Filtro inválido: '.$campo]);
    $valor=trim($valor);
    if (strlen($valor) > $limite * 4) resposta(400,['ok'=>false,'erro'=>'Campo muito longo: '.$campo]);
    if (preg_match('/[\x00-\x08\x0B\x0C\x0E-\x1F]/', $valor)) resposta(400,['ok'=>false,'erro'=>'Caracteres inválidos no filtro.']);
    if ($valor !== '') $filtros[$campo]=$valor;
}
if (isset($filtros['numeroOab']) && !preg_match('/^[a-zA-Z0-9.\/\-]+$/', $filtros['numeroOab'])) {
    resposta(400,['ok'=>false,'erro'=>'Número da OAB inválido.']);
}
if (isset($filtros['numeroProcesso'])) {
    $filtros['numeroProcesso']=preg_replace('/\D+/', '', $filtros['numeroProcesso']);
    if (strlen($filtros['numeroProcesso']) < 8 || strlen($filtros['numeroProcesso']) > 25) {
        resposta(400,['ok'=>false,'erro'=>'Confira o número do processo.']);
    }
}
if (isset($filtros['ufOab'])) {
    $filtros['ufOab']=strtoupper($filtros['ufOab']);
    if (!preg_match('/^[A-Z]{2}$/', $filtros['ufOab'])) resposta(400,['ok'=>false,'erro'=>'UF da OAB inválida.']);
    if (empty($filtros['numeroOab'])) resposta(400,['ok'=>false,'erro'=>'Preencha o número da OAB ou deixe a UF vazia.']);
}
if (isset($filtros['siglaTribunal'])) {
    $filtros['siglaTribunal']=strtoupper($filtros['siglaTribunal']);
    if (!preg_match('/^[A-Z0-9]{2,12}$/', $filtros['siglaTribunal'])) resposta(400,['ok'=>false,'erro'=>'Sigla de tribunal inválida.']);
}
if (isset($filtros['meio']) && !in_array($filtros['meio'],['D','E'],true)) {
    resposta(400,['ok'=>false,'erro'=>'Tipo de meio inválido.']);
}
foreach (['dataDisponibilizacaoInicio','dataDisponibilizacaoFim'] as $nome) {
    if (!isset($filtros[$nome])) continue;
    $date=DateTimeImmutable::createFromFormat('!Y-m-d',$filtros[$nome]);
    if (!$date || $date->format('Y-m-d') !== $filtros[$nome]) resposta(400,['ok'=>false,'erro'=>'Data inválida.']);
}
if (isset($filtros['dataDisponibilizacaoInicio']) xor isset($filtros['dataDisponibilizacaoFim'])) {
    resposta(400,['ok'=>false,'erro'=>'Preencha as duas datas ou deixe ambas vazias.']);
}
if (isset($filtros['dataDisponibilizacaoInicio']) && $filtros['dataDisponibilizacaoInicio'] > $filtros['dataDisponibilizacaoFim']) {
    resposta(400,['ok'=>false,'erro'=>'A data inicial não pode ser posterior à final.']);
}
$buscas = ['numeroOab','nomeAdvogado','numeroProcesso','nomeParte','siglaTribunal','texto'];
$temBusca=false;
foreach ($buscas as $chave) if (isset($filtros[$chave])) $temBusca=true;
if (!$temBusca) resposta(400,['ok'=>false,'erro'=>'Informe ao menos um filtro: tribunal, processo, nome, OAB ou teor.']);

$pagina=filter_var($_GET['pagina'] ?? '1', FILTER_VALIDATE_INT, ['options'=>['min_range'=>1,'max_range'=>10000]]);
if ($pagina===false) resposta(400,['ok'=>false,'erro'=>'Página inválida.']);
// Tamanho 100 conforme integração já utilizada no sistema original; UI mostra 20/50/100 por vez.
$filtros['pagina']=(string)$pagina;
$filtros['itensPorPagina']='100';
$url='https://comunicaapi.pje.jus.br/api/v1/comunicacao?'.http_build_query($filtros,'','&',PHP_QUERY_RFC3986);
$body=''; $status=0; $erroRede=''; $retryAfter=null;
if (function_exists('curl_init')) {
    $curl=curl_init($url);
    curl_setopt_array($curl,[
        CURLOPT_RETURNTRANSFER=>true, CURLOPT_FOLLOWLOCATION=>false,
        CURLOPT_CONNECTTIMEOUT=>7, CURLOPT_TIMEOUT=>25,
        CURLOPT_SSL_VERIFYPEER=>true, CURLOPT_SSL_VERIFYHOST=>2,
        CURLOPT_ENCODING=>'',
        CURLOPT_HTTPHEADER=>['Accept: application/json', 'User-Agent: ConsultaDJEN-Leve/1.0']
    ]);
    curl_setopt($curl,CURLOPT_HEADERFUNCTION,static function($ch,$linha) use (&$retryAfter){
        if (stripos($linha, 'Retry-After:')===0) $retryAfter=trim(substr($linha,12));
        return strlen($linha);
    });
    $resultado=curl_exec($curl);
    $status=(int)curl_getinfo($curl,CURLINFO_HTTP_CODE);
    if ($resultado===false) $erroRede=curl_error($curl);
    else $body=(string)$resultado;
    curl_close($curl);
} elseif (ini_get('allow_url_fopen')) {
    $contexto=stream_context_create(['http'=>[
        'method'=>'GET','timeout'=>25,'ignore_errors'=>true,'follow_location'=>0,
        'header'=>"Accept: application/json\r\nUser-Agent: ConsultaDJEN-Leve/1.0\r\n"
    ]]);
    $resultado=@file_get_contents($url,false,$contexto);
    if ($resultado===false) $erroRede='Falha na conexão HTTPS com o CNJ.';
    else $body=$resultado;
    foreach (($http_response_header ?? []) as $linha) {
        if (preg_match('/^HTTP\/\S+\s+(\d{3})/', $linha,$m)) $status=(int)$m[1];
        if (stripos($linha,'Retry-After:')===0) $retryAfter=trim(substr($linha,12));
    }
} else {
    resposta(500,['ok'=>false,'erro'=>'PHP sem cURL e allow_url_fopen. Habilite a extensão cURL.']);
}
if ($erroRede!=='') resposta(502,['ok'=>false,'erro'=>'Não foi possível conectar à API do CNJ. Verifique o HTTPS de saída da VPS.','detalhe'=>$erroRede]);
if ($status===429) {
    http_response_code(429);
    if (is_string($retryAfter) && preg_match('/^\d{1,4}$/',$retryAfter)) header('Retry-After: '.$retryAfter);
    resposta(429,['ok'=>false,'erro'=>'A API do CNJ atingiu o limite de consultas. Aguarde antes de pesquisar novamente.']);
}
if ($status<200 || $status>=300) {
    $obj=json_decode($body,true);
    $msg='A API do CNJ respondeu com HTTP '.$status.'.';
    if (is_array($obj)) foreach (['message','mensagem','detail','error','erro'] as $k) {
        if (isset($obj[$k]) && is_string($obj[$k])) { $msg.=' '.substr($obj[$k],0,280);break; }
    }
    resposta($status>=400 && $status<500 ? 422 : 502,['ok'=>false,'erro'=>$msg,'codigo_cnj'=>$status]);
}
$obj=json_decode($body,true);
if (!is_array($obj)) resposta(502,['ok'=>false,'erro'=>'O CNJ retornou dados em formato inesperado.']);
$registros=$obj['items'] ?? $obj['comunicacoes'] ?? $obj['content'] ?? $obj['data'] ?? [];
if (!is_array($registros)) resposta(502,['ok'=>false,'erro'=>'A resposta do CNJ não contém uma lista válida.']);

function valorTexto(array $a, array $chaves): string {
    foreach ($chaves as $k) {
        if (isset($a[$k]) && (is_string($a[$k]) || is_numeric($a[$k]))) return trim((string)$a[$k]);
    }
    return '';
}
function plano(string $v): string {
    $v=preg_replace('/<\s*br\b[^>]*>/iu',"\n",$v);
    $v=preg_replace('/<\s*\/\s*(p|div|li|tr|h[1-6])\s*>/iu',"\n",$v);
    $v=strip_tags($v);
    $v=html_entity_decode($v,ENT_QUOTES|ENT_HTML5,'UTF-8');
    $v=str_replace("\xC2\xA0",' ',$v);
    $v=preg_replace('/[ \t]+/u',' ',$v);
    $v=preg_replace('/\n{3,}/',"\n\n",$v);
    return trim($v);
}
$itens=[];
foreach ($registros as $r) {
    if (!is_array($r)) continue;
    $texto=valorTexto($r,['texto','teor','conteudo','teorPublicacao']);
    $processo=valorTexto($r,['numeroprocessocommascara','numeroProcessoComMascara','numeroProcesso','numero_processo']);
    $partes=[];
    foreach (['destinatarios','destinatarioadvogados','partes'] as $key) {
        if (empty($r[$key]) || !is_array($r[$key])) continue;
        foreach ($r[$key] as $p) {
            if (is_string($p)) $partes[]=$p;
            elseif (is_array($p)) {
                $n=valorTexto($p,['nome','nomeDestinatario','nomeParte','nomeAdvogado']);
                if ($n!=='') $partes[]=$n;
            }
        }
    }
    $destino=valorTexto($r,['nomeDestinatario']);
    if ($destino!=='') $partes[]=$destino;
    $hash=valorTexto($r,['hash']);
    $itens[]=[
        'id'=>valorTexto($r,['id','hash']),
        'hash'=>$hash,
        'processo'=>$processo,
        'tribunal'=>valorTexto($r,['siglaTribunal','sigla_tribunal']),
        'orgao'=>valorTexto($r,['nomeOrgao','nome_orgao']),
        'classe'=>valorTexto($r,['nomeClasse','nome_classe']),
        'tipo'=>valorTexto($r,['tipoComunicacao','tipo_comunicacao']),
        'data'=>valorTexto($r,['dataDisponibilizacao','data_disponibilizacao']),
        'partes'=>array_slice(array_values(array_unique($partes)),0,15),
        'texto'=>plano($texto)
    ];
}
$total=null;
foreach (['count','total','totalElements','totalRegistros'] as $key) {
    if (isset($obj[$key]) && is_numeric($obj[$key])) { $total=max(0,(int)$obj[$key]); break; }
}
resposta(200,[
    'ok'=>true, 'pagina'=>(int)$pagina, 'tamanho_lote'=>100,
    'total'=>$total, 'itens'=>$itens,
    'fonte'=>'API pública do CNJ — DJEN',
    'aviso'=>$total !== null && $total>=10000 ? 'A API do CNJ pode limitar buscas amplas a 10.000 resultados. Refine os filtros/período.' : null
]);
