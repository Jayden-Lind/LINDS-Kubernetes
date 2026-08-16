try {
    var params = JSON.parse(value),
        request = new HttpRequest(),
        data,
        response;

    if (typeof params.HTTPProxy === 'string' && params.HTTPProxy.trim() !== '') {
        request.SetProxy(params.HTTPProxy);
    }

    data = {
        token: params.token,
        title: params.title,
        desc: params.message
    };

    data = JSON.stringify(data);
    Zabbix.Log(4, '[ ZBXViewer Webhook ] Sending request: ' + params.endpoint + '\n' + data);

    request.addHeader('Content-Type: application/json');
    response = request.post(params.endpoint, data);


    Zabbix.Log(4, '[ ZBXViewer Webhook ] Received response with status code ' + request.getStatus() + '\n' + response);

    if (response !== null) {
        try {
            response = JSON.parse(response);
        }
        catch (error) {
            Zabbix.Log(4, '[ ZBXViewer Webhook ] Failed to parse response received from ZBXViewer');
            response = null;
        }
    }

    if (request.getStatus() != 200) {
        if (response !== null && typeof response === 'object' && typeof response.errors === 'object'
                && typeof response.errors[0] === 'string') {
            throw response.errors[0];
        }
        else {
            throw 'Unknown error. Check debug log for more information.';
        }
    }

    return 'OK';
}
catch (error) {
    Zabbix.Log(4, '[ ZBXViewer Webhook ] ZBXViewer notification failed: ' + error);
    throw 'ZBXViewer notification failed: ' + error;
}