(function () {
  var body = document.body;
  document.querySelectorAll('[data-sidebar-open]').forEach(function (button) { button.addEventListener('click', function () { body.classList.add('sidebar-open'); }); });
  document.querySelectorAll('[data-sidebar-close]').forEach(function (button) { button.addEventListener('click', function () { body.classList.remove('sidebar-open'); }); });
  var topbar = document.querySelector('.topbar');
  document.querySelectorAll('[data-search-open]').forEach(function (button) { button.addEventListener('click', function () { topbar.classList.toggle('search-open'); document.getElementById('global-search-input')?.focus(); }); });

  var drawer = document.getElementById('drawer');
  var drawerContent = document.getElementById('drawer-content');
  function closeDrawer() { if (!drawer) return; drawer.hidden = true; drawer.setAttribute('aria-hidden', 'true'); drawerContent.innerHTML = ''; }
  document.querySelectorAll('[data-drawer-close]').forEach(function (button) { button.addEventListener('click', closeDrawer); });
  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-drawer-url]');
    if (!trigger) return;
    trigger.disabled = true;
    drawerContent.innerHTML = '<div class="empty-state"><div class="empty-state__icon">…</div><h3>Загрузка</h3></div>';
    drawer.hidden = false; drawer.setAttribute('aria-hidden', 'false');
    fetch(trigger.dataset.drawerUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (response) { if (!response.ok) throw new Error(); return response.text(); })
      .then(function (html) { drawerContent.innerHTML = html; drawer.hidden = false; drawer.setAttribute('aria-hidden', 'false'); drawer.querySelector('.drawer__close').focus(); })
      .catch(function () { window.location.href = trigger.dataset.drawerUrl.replace('/quick/', '/'); })
      .finally(function () { trigger.disabled = false; });
  });

  var modal = document.getElementById('confirm-modal');
  var pendingForm = null;
  var pendingAction = null;
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (form.dataset.confirmed === 'true') return;
      event.preventDefault(); pendingForm = form;
      document.getElementById('confirm-message').textContent = form.dataset.confirm;
      modal.hidden = false; modal.setAttribute('aria-hidden', 'false');
      document.getElementById('confirm-submit').focus();
    });
  });
  document.querySelectorAll('[data-danger-action]').forEach(function (button) {
    button.addEventListener('click', function () {
      var form = button.closest('form');
      var comment = form?.querySelector('textarea[name="comment"]');
      if (comment && !comment.value.trim()) { comment.focus(); comment.setCustomValidity('Укажите причину отклонения'); comment.reportValidity(); return; }
      if (comment) comment.setCustomValidity('');
      pendingForm = form; pendingAction = button.dataset.dangerAction;
      document.getElementById('confirm-message').textContent = button.dataset.dangerMessage;
      modal.hidden = false; modal.setAttribute('aria-hidden', 'false');
      document.getElementById('confirm-submit').focus();
    });
  });
  function closeModal() { if (!modal) return; modal.hidden = true; modal.setAttribute('aria-hidden', 'true'); pendingForm = null; pendingAction = null; }
  document.querySelectorAll('[data-modal-close]').forEach(function (button) { button.addEventListener('click', closeModal); });
  document.getElementById('confirm-submit')?.addEventListener('click', function () { if (!pendingForm) return; pendingForm.dataset.confirmed = 'true'; if (pendingAction) pendingForm.action = pendingAction; pendingForm.requestSubmit(); });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { closeDrawer(); closeModal(); body.classList.remove('sidebar-open'); } });

  document.querySelectorAll('[data-toast]').forEach(function (toast) {
    window.setTimeout(function () { toast.classList.add('is-leaving'); window.setTimeout(function () { toast.remove(); }, 220); }, 4200);
  });
  document.querySelectorAll('.document-card img').forEach(function (img) {
    function showError() {
      var replacement = document.createElement('div');
      replacement.className = 'document-empty';
      replacement.textContent = 'Не удалось загрузить изображение';
      img.replaceWith(replacement);
    }
    img.addEventListener('error', showError, { once: true });
    if (img.complete && !img.naturalWidth) showError();
  });
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function () {
      window.setTimeout(function () { form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = true; }); }, 0);
    });
  });
})();
