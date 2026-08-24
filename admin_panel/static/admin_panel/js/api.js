(function () {
  function cookie(name) {
    return document.cookie.split(';').map(function (part) { return part.trim(); })
      .find(function (part) { return part.indexOf(name + '=') === 0; })
      ?.split('=').slice(1).join('=');
  }
  window.SafaAPI = {
    request: function (url, options) {
      options = options || {};
      options.headers = Object.assign({
        'X-CSRFToken': decodeURIComponent(cookie('csrftoken') || ''),
        'X-Requested-With': 'XMLHttpRequest'
      }, options.headers || {});
      return fetch(url, options).then(function (response) {
        if (!response.ok) return response.json().catch(function () { return {}; }).then(function (data) { throw data; });
        return response.json();
      });
    }
  };
})();
