(function () {
  var root = document.querySelector('[data-global-search]');
  if (!root) return;
  var input = root.querySelector('input');
  var results = document.getElementById('global-search-results');
  var timer;
  function escapeHTML(value) { var node = document.createElement('div'); node.textContent = value || ''; return node.innerHTML; }
  function hide() { results.hidden = true; results.innerHTML = ''; }
  input.addEventListener('input', function () {
    window.clearTimeout(timer);
    var query = input.value.trim();
    if (query.length < 2) { hide(); return; }
    timer = window.setTimeout(function () {
      results.innerHTML = '<div class="empty-state" style="padding:20px">Поиск…</div>';
      results.hidden = false;
      fetch('/panel/search/?q=' + encodeURIComponent(query), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (!data.groups.length) { results.innerHTML = '<div class="empty-state" style="padding:24px">Ничего не найдено</div>'; }
          else results.innerHTML = data.groups.map(function (group) {
            return '<section class="search-group"><div class="search-group__label">' + escapeHTML(group.label) + '</div>' + group.items.map(function (item) {
              return '<a class="search-result" href="' + encodeURI(item.url) + '"><strong>' + escapeHTML(item.title) + '</strong><small>' + escapeHTML(item.meta) + '</small></a>';
            }).join('') + '</section>';
          }).join('');
          results.hidden = false;
        }).catch(hide);
    }, 300);
  });
  document.addEventListener('click', function (event) { if (!root.contains(event.target)) hide(); });
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') hide();
    if (event.key === 'Enter') {
      var first = results.querySelector('.search-result');
      if (first) { event.preventDefault(); window.location.href = first.href; }
    }
  });
})();
