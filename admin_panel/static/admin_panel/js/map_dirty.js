(function () {
  var root = document.getElementById('market-map-editor');
  var status = document.getElementById('market-map-status');
  var label = document.getElementById('market-map-dirty-label');
  if (!root || !status || !label) return;
  var dirty = false;
  var objectsPanel = root.querySelector('.market-map-objects-panel');
  var leftPanel = root.querySelector('.market-map-create-panel');
  if (objectsPanel && leftPanel) {
    objectsPanel.open = true;
    leftPanel.appendChild(objectsPanel);
  }
  var addToggle = document.getElementById('map-add-toggle');
  var createMenu = document.getElementById('map-create-menu');
  addToggle?.addEventListener('click', function () {
    createMenu.hidden = !createMenu.hidden;
    addToggle.textContent = createMenu.hidden ? '+ Добавить' : 'Закрыть';
  });
  createMenu?.addEventListener('click', function (event) {
    if (event.target.closest('[data-map-kind]')) {
      createMenu.hidden = true;
      addToggle.textContent = '+ Добавить';
    }
  });
  document.getElementById('map-bazar-select')?.addEventListener('change', function (event) {
    if (!dirty || window.confirm('На карте есть несохранённые изменения. Перейти к другому базару?')) {
      window.location.href = event.target.value;
    } else {
      event.target.value = window.location.pathname;
    }
  });
  var objectSearch = document.getElementById('map-object-search');
  var featureList = document.getElementById('market-feature-list');
  function filterObjects() {
    var query = (objectSearch?.value || '').trim().toLowerCase();
    featureList?.querySelectorAll(':scope > *').forEach(function (item) {
      item.hidden = Boolean(query && !item.textContent.toLowerCase().includes(query));
    });
  }
  objectSearch?.addEventListener('input', filterObjects);
  if (featureList) new MutationObserver(filterObjects).observe(featureList, { childList: true });
  function setDirty(value) { dirty = value; label.hidden = !value; }
  root.addEventListener('market-map:dirty', function () { setDirty(true); });
  root.addEventListener('change', function (event) {
    if (event.target.closest('.market-map-properties')) setDirty(true);
  });
  root.addEventListener('click', function (event) {
    if (event.target.closest('[data-map-kind], #market-map-finish, #market-feature-apply, #market-feature-delete, #market-feature-duplicate')) setDirty(true);
  });
  new MutationObserver(function () {
    var message = status.textContent || '';
    if (message.indexOf('сохранён') !== -1 || message.indexOf('опубликована') !== -1) setDirty(false);
  }).observe(status, { childList: true, subtree: true, characterData: true });
  // Удаление карты уносит и несохранённый черновик — предупреждать не о чем.
  document.addEventListener('submit', function (event) {
    if (event.target.closest('[data-map-discard]')) setDirty(false);
  }, true);
  window.addEventListener('beforeunload', function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
