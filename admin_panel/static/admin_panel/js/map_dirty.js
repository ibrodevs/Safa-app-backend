(function () {
  var root = document.getElementById('market-map-editor');
  var status = document.getElementById('market-map-status');
  var label = document.getElementById('market-map-dirty-label');
  if (!root || !status || !label) return;
  var dirty = false;
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
  window.addEventListener('beforeunload', function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
