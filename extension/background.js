chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state || delta.state.current !== 'complete') return;

  chrome.downloads.search({ id: delta.id }).then((results) => {
    if (!results.length) return;

    const item = results[0];
    const msg = {
      source:   'chrome',
      detector: 'chrome_extension',
      filename: item.filename.split('\\').pop().split('/').pop(),
      path:     item.filename,
      size:     item.fileSize,
      mime:     item.mime,
      final_url: item.finalUrl || '',
    };

    chrome.runtime.sendNativeMessage('com.dropdone.host', msg, (response) => {
      if (chrome.runtime.lastError) {
        console.error('[DropDone] Native messaging error:', chrome.runtime.lastError.message);
        return;
      }
      if (!response || response.status !== 'ok') {
        console.error('[DropDone] Native host rejected message:', response?.error || response);
      }
    });
  });
});
