// institution-payment.html (Phase 11): choose monthly / yearly, pay on Safepay's page, come back here.
// Opened with a signed ?token= (the institution cannot sign in before paying). Coming back from Safepay, the page asks
// OUR server to check the payment with Safepay (POST /payments/confirm); the URL alone never counts as paid.
const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const TOKEN = params.get('token') || '';
let INFO = null, PLAN = null;

const money = (n, cur = 'PKR') => `${cur} ${Number(n).toLocaleString('en-PK', { maximumFractionDigits: 0 })}`;
const dateText = iso => iso ? new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' }) : '';
function showErr(msg) { $('authErr').textContent = msg; $('authErr').style.display = msg ? 'block' : 'none'; }
function showOk(msg) { $('authOk').textContent = msg; $('authOk').style.display = msg ? 'block' : 'none'; }
function steps(n) {
  $('stepPay').classList.toggle('on', n === 2);
  $('stepReview').classList.toggle('on', n === 3);
}

function renderPlans() {
  $('plans').innerHTML = INFO.plans.map(p => `
    <label class="plan ${PLAN === p.id ? 'on' : ''}">
      <input type="radio" name="plan" value="${esc(p.id)}" ${PLAN === p.id ? 'checked' : ''} />
      <span class="plan-name">${esc(p.label)}${p.saving ? ` <span class="plan-save">Save ${esc(money(p.saving))}</span>` : ''}</span>
      <span class="plan-price">${esc(money(p.amount, p.currency))}<small>/${p.months === 1 ? 'month' : 'year'}</small></span>
      <span class="plan-note">${esc(p.note)}</span>
    </label>`).join('');
  $('plans').querySelectorAll('input').forEach(i => i.addEventListener('change', () => { PLAN = i.value; renderPlans(); }));
  const plan = INFO.plans.find(p => p.id === PLAN);
  $('payBtn').disabled = !plan || !INFO.gateway.configured;
  $('payBtn').innerHTML = plan ? `Pay ${esc(money(plan.amount, plan.currency))} with Safepay <i data-icon="arrow-right"></i>` : 'Choose a plan';
  if (window.AIcons) window.AIcons.hydrate($('planBox'));
}

function result(html, kind) {
  $('planBox').hidden = true;
  $('result').hidden = false;
  $('result').className = 'pay-result ' + (kind || '');
  $('result').innerHTML = html;
}

function paidScreen(p) {
  steps(3);
  const reg = p.purpose === 'registration';
  $('ttl').textContent = 'Payment received';
  $('lead').textContent = reg ? 'Your registration is now waiting for approval.' : 'Your subscription is renewed.';
  result(`<div class="pay-big">✓</div>
    <dl class="pay-receipt">
      <dt>Amount</dt><dd>${esc(money(p.amount, p.currency))}</dd>
      <dt>Plan</dt><dd>${esc(p.plan === 'yearly' ? 'Yearly' : 'Monthly')}</dd>
      <dt>Receipt</dt><dd class="mono">${esc(p.receipt_no || '')}</dd>
      <dt>Safepay reference</dt><dd class="mono">${esc(p.reference || '')}</dd>
      ${p.card_hint ? `<dt>Paid with</dt><dd>${esc(p.card_hint)}</dd>` : ''}
    </dl>
    <p>${reg ? 'We have emailed you the receipt. The Assessify team will now review your registration; you will get an email when it is approved, and then you can sign in.'
             : `We have emailed you the receipt. Your subscription is valid until ${esc(dateText(INFO?.institution?.paid_until))}.`}</p>
    <a class="btn btn-primary btn-block" href="institution-login.html">Go to sign in</a>`, 'ok');
}

function failedScreen(p, why) {
  steps(2);
  $('ttl').textContent = 'Payment not completed';
  $('lead').textContent = 'No money was taken for this attempt.';
  result(`<p class="pay-why">${esc(why || p?.failure_reason || 'The payment did not go through.')}</p>
    <p>We have also emailed you a link to try again. You can try again now with the same or another card.</p>
    <button type="button" class="btn btn-primary btn-block" id="retryBtn">Try again</button>`, 'bad');
  $('retryBtn').addEventListener('click', () => { history.replaceState(null, '', '?token=' + encodeURIComponent(TOKEN)); void load(); });
}

async function load() {
  showErr(''); showOk('');
  $('result').hidden = true;
  if (!TOKEN) { $('lead').textContent = ''; return showErr('This page needs a payment link. Sign in with your email and password to open it.'); }
  try { INFO = await api('/payments/session?token=' + encodeURIComponent(TOKEN)); }
  catch (e) { $('lead').textContent = ''; return showErr(e.message); }
  const inst = INFO.institution, purpose = INFO.purpose;
  $('testMode').hidden = !(INFO.gateway.enabled && INFO.gateway.environment === 'sandbox');
  if (!purpose) {
    if (inst.status === 'pending') {
      steps(3);
      $('ttl').textContent = 'Payment received';
      $('lead').textContent = `${inst.name} has paid. The registration is waiting for approval; you will get an email.`;
      return;
    }
    $('lead').textContent = '';
    return showErr(inst.status === 'approved' ? 'Your institution is active; no payment is due. Sign in instead.'
      : 'No payment is possible for this institution. Please contact the platform team.');
  }
  $('ttl').textContent = purpose === 'renewal' ? 'Renew your subscription' : 'Subscription payment';
  $('lead').textContent = purpose === 'renewal'
    ? `${inst.name}: ${inst.expired ? 'your subscription has ended' : 'your subscription is active until ' + dateText(inst.paid_until)}. Choose a plan to ${inst.expired ? 'continue' : 'extend it'}.`
    : `${inst.name} is registered. Choose a plan and pay to send the registration for approval.`;
  if (!INFO.gateway.configured) showErr(INFO.gateway.message || 'Payments are not set up on the server yet.');
  PLAN = PLAN || inst.plan || 'yearly';
  $('planBox').hidden = false;
  renderPlans();
}

async function pay() {
  const btn = $('payBtn'); btn.disabled = true; btn.textContent = 'Opening Safepay…'; showErr('');
  try {
    const r = await api('/payments/checkout', { method: 'POST', body: { token: TOKEN, plan: PLAN, return_url: location.href.split('?')[0] } });
    location.href = r.checkout_url;                    // Safepay's hosted, secure checkout page
  } catch (e) {
    showErr(e.message); renderPlans();
  }
}

// back from Safepay: ask our server (which asks Safepay) - a few times, Safepay can take a moment to finish
async function returned(paymentId, tracker, cancelled) {
  $('planBox').hidden = true;
  $('ttl').textContent = cancelled ? 'Payment cancelled' : 'Checking your payment…';
  $('lead').textContent = cancelled ? '' : 'Asking Safepay to confirm the payment. This takes a few seconds.';
  for (let i = 0; i < 10; i++) {
    let r;
    try {
      r = await api(cancelled ? '/payments/cancel' : '/payments/confirm', { method: 'POST', body: { token: TOKEN, payment: paymentId, tracker } });
    } catch (e) {
      if (i === 9 || e.status === 400 || e.status === 404 || e.status === 410) return failedScreen(null, e.message);
      await new Promise(res => setTimeout(res, 3000)); continue;
    }
    const p = r.payment;
    if (p.status === 'paid') { try { INFO = await api('/payments/session?token=' + encodeURIComponent(TOKEN)); } catch (e) { /* receipt still shows */ } return paidScreen(p); }
    if (p.status === 'failed' || p.status === 'cancelled') return failedScreen(p);
    if (cancelled) return failedScreen(p, 'You cancelled the payment.');
    await new Promise(res => setTimeout(res, 3000));
  }
  failedScreen(null, 'Safepay has not confirmed the payment yet. If money was taken, it will be matched automatically; check your email, or sign in again in a few minutes.');
}

document.addEventListener('DOMContentLoaded', () => {
  $('payBtn').addEventListener('click', () => void pay());
  // Safepay may tack its own "?tracker=..." onto our address, so payment can arrive as "12?tracker=track_..."
  const back = (params.get('result') || '').split('?')[0];
  const rawPay = params.get('payment') || '';
  const paymentId = (rawPay.match(/^\d+/) || [''])[0];
  const tracker = params.get('tracker') || (location.href.match(/[?&]tracker=([^&#]+)/) || [])[1] || '';
  if (back) void returned(paymentId, decodeURIComponent(tracker), back === 'cancel');
  else void load();
});
