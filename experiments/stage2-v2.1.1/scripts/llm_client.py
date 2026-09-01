from __future__ import annotations
import json, os, time, urllib.error, urllib.request

class LLMError(RuntimeError): pass

def chat_completion(llm_cfg: dict, messages: list[dict]):
    key=os.environ.get(llm_cfg['api_key_env'],'')
    if not key: raise LLMError(f"Missing environment variable {llm_cfg['api_key_env']}")
    base=llm_cfg['api_base'].rstrip('/')
    url=base + '/chat/completions'
    payload={
        'model':llm_cfg['model'], 'messages':messages,
        'temperature':llm_cfg['temperature'], 'top_p':llm_cfg['top_p'],
        'max_tokens':llm_cfg['max_output_tokens']
    }
    thinking=llm_cfg.get('thinking')
    if thinking is not None:
        payload['thinking']=thinking
    # DeepSeek reasoning_effort only applies to enabled Thinking mode.  Never
    # leak a stale reasoning setting into the non-reasoning experiment.
    if (isinstance(thinking,dict) and thinking.get('type')=='enabled'
            and llm_cfg.get('reasoning_effort')):
        payload['reasoning_effort']=llm_cfg['reasoning_effort']
    body=json.dumps(payload).encode('utf-8')
    last=None
    for attempt in range(int(llm_cfg.get('network_retries',3))):
        req=urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization':f'Bearer {key}','Content-Type':'application/json'
        })
        try:
            with urllib.request.urlopen(req, timeout=int(llm_cfg['timeout_seconds'])) as resp:
                data=json.loads(resp.read().decode('utf-8'))
            choice=data['choices'][0]
            message=choice.get('message',{})
            content=message.get('content','')
            if content is None:
                content=''
            if isinstance(content,list):
                content=''.join(x.get('text','') if isinstance(x,dict) else str(x) for x in content)
            usage=data.get('usage',{})
            return {
                'content':content,
                'finish_reason':choice.get('finish_reason'),
                'has_reasoning_content':bool(message.get('reasoning_content')),
                'input_tokens':int(usage.get('prompt_tokens', usage.get('input_tokens',0)) or 0),
                'output_tokens':int(usage.get('completion_tokens', usage.get('output_tokens',0)) or 0),
                'raw':data
            }
        except Exception as e:
            last=e
            if attempt+1 < int(llm_cfg.get('network_retries',3)): time.sleep(2**attempt)
    raise LLMError(str(last))
