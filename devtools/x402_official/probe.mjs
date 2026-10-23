/** Official @x402/core SDK read-only verification probe. NEVER calls settle. */
import assert from "node:assert/strict";
import { HTTPFacilitatorClient, encodePaymentRequiredHeader,
  decodePaymentRequiredHeader, encodePaymentSignatureHeader,
  decodePaymentSignatureHeader } from "@x402/core/http";

const network = "eip155:84532";
const requirements = {
  scheme:"exact",network,amount:"20000",
  asset:"0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  payTo:"0x0000000000000000000000000000000000000002",
  maxTimeoutSeconds:60,extra:{name:"USDC",version:"2"}
};
const resource={url:"http://127.0.0.1:0/sandbox/resource",mimeType:"application/json"};
const required={x402Version:2,resource,accepts:[requirements],extensions:{}};
const payment={
  x402Version:2,resource,accepted:requirements,extensions:{},
  payload:{
    signature:"0x"+"00".repeat(65),
    authorization:{
      from:"0x0000000000000000000000000000000000000001",
      to:requirements.payTo,value:requirements.amount,validAfter:"0",
      validBefore:"9999999999",nonce:"0x"+"00".repeat(32)
    }
  }
};
assert.deepEqual(decodePaymentRequiredHeader(encodePaymentRequiredHeader(required)),required);
assert.deepEqual(decodePaymentSignatureHeader(encodePaymentSignatureHeader(payment)),payment);
const client=new HTTPFacilitatorClient({url:"https://x402.org/facilitator",timeoutMs:9000});
// Intentionally no settle function in this exposed interface.
const verifyOnly=Object.freeze({
  getSupported:()=>client.getSupported(),
  verify:(p,r)=>client.verify(p,r)
});
const out={sdk:"@x402/core@2.28.0",header_roundtrip:true,
  endpoint:"https://x402.org/facilitator",
  attempted:["GET /supported"],settlement_attempted:false,
  real_funds_transferred:false,invalid_signature:true};
try {
  const supported=await verifyOnly.getSupported();
  const kinds=Array.isArray(supported?.kinds)?supported.kinds:[];
  out.supported_kinds=kinds.length;
  out.exact_base_sepolia=kinds.some(k=>k.x402Version===2&&
    k.scheme==="exact"&&k.network===network);
  if(!out.exact_base_sepolia)throw Error("testnet_exact_not_advertised");
  out.attempted.push("POST /verify");
  const result=await verifyOnly.verify(payment,requirements);
  out.verify_response_is_valid=result?.isValid;
  if(result?.isValid!==false)throw Error("invalid_signature_not_rejected");
  out.negative_verification_passed=true;
  out.status="passed";
}catch(e){
  out.status="blocked_or_incompatible";
  out.error_type=e?.name||"Error";
  out.error=String(e?.message||e).slice(0,130);
  process.exitCode=2;
}
console.log(JSON.stringify(out,null,2));
