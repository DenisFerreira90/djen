'use strict';
function chatVisibleEnough(message,viewport){const h=Math.min(message.bottom,viewport.bottom)-Math.max(message.top,viewport.top);return h>0&&h>=Math.min(message.bottom-message.top,viewport.bottom-viewport.top)*.5;}
function chatReceiptLabel(receipt){if(!receipt)return '';return receipt.estado==='visualizada'?'✓✓ Visualizada':receipt.estado==='recebida'?'✓✓ Recebida':receipt.visualizadas?`✓ Enviada · ${receipt.visualizadas}/${receipt.total} visualizaram`:'✓ Enviada';}
if(typeof module!=='undefined'&&module.exports)module.exports={chatVisibleEnough,chatReceiptLabel};
if(typeof window!=='undefined')window.ChatView={visibleEnough:chatVisibleEnough,receiptLabel:chatReceiptLabel};
