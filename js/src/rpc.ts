const registeredFunctions: Map<string, Function> = new Map();
const callbacks: Map<string, [Function, Function]> = new Map();

let ws: WebSocket | null = null;

export function registerFunction(name: string, f: Function) {
    registeredFunctions.set(name, f);
}

function test(a: number) {
    console.info(`Got call to test(${a})`);
    return a+1;
}
registerFunction("test", test);

export function call(name: string, ...args: any[]) {
    let callId = crypto.randomUUID();
    let data = {
        type: "request",
        callId: callId,
        name: name,
        args: args,
    }
    if (!ws) {
        console.error("Websocket not open. Cannot send message");
        return;
    }

    return new Promise((resolve, reject) => {
        callbacks.set(callId, [resolve, reject]);
        ws?.send(JSON.stringify(data));
    });
}

export function connect(url: string) {
    console.info("Attempting to connect")
    ws = new WebSocket(url);
    ws.addEventListener("open", wsOpenEvent);
    ws.addEventListener("close", wsCloseEvent);
    ws.addEventListener("message", wsMessageEvent);
    ws.addEventListener("error", wsErrorEvent);

}

function wsMessageEvent(event: MessageEvent) {
    console.debug("Got RPC event", event.data);
    let data = JSON.parse(event.data);
    let type = data["type"]
    if (type == "request") {
        let callId = data["callId"];
        let name = data["name"];
        let args = data["args"];

        let f = registeredFunctions.get(name);
        if (!f) {
            ws?.send(JSON.stringify({
                type: "response",
                callId: callId,
                error: "No such function",
            }))
            return;
        }
        let ret;

        function onSuccess(value: any) {
            ws?.send(JSON.stringify({
                type: "response",
                callId: callId,
                retVal: value,
            }))
        }

        function onError(e: any) {
            ws?.send(JSON.stringify({
                type: "response",
                callId: callId,
                error: e,
            }))
        }

        try {
            ret = f(...args);
        } catch (e) {
            onError(e);
            return;
        }

        Promise.resolve(ret).then(onSuccess, onError);

    } else if (type == "response") {
        let callId = data["callId"];
        let retVal = data["retVal"];
        let error = data["error"];
        let cb = callbacks.get(callId);
        callbacks.delete(callId);
        if (!cb) {
            console.error(`Returned call ${callId} but no callId exists in callback map`);
            return;
        }
        let [resolve, reject] = cb;
        if (error) {
            reject(error);
        }
        resolve(retVal);
    }
}

function wsCloseEvent(event: CloseEvent) {
    console.debug("Websocket closed", event)
}

function wsErrorEvent(event: Event) {
    console.debug("Websocket errored", event)
}

function wsOpenEvent(event: Event) {
    console.debug("websocket opened", event)
}