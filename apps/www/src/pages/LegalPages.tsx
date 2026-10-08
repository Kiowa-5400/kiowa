import type { ReactNode } from 'react';
import { Link, usePageTitle } from '@shared/router';
import { useSite } from '../site';

// Update this date whenever either page's wording changes.
const EFFECTIVE = 'October 7, 2026';

function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <header className="page-hero">
        <p className="kicker">Effective {EFFECTIVE}</p>
        <h1>{title}</h1>
      </header>
      <article className="card legal">{children}</article>
    </>
  );
}

function Contact() {
  const { site } = useSite();
  return (
    <p>
      {site.site_title}
      {site.mailing_address && <><br /><span style={{ whiteSpace: 'pre-line' }}>{site.mailing_address}</span></>}
      {site.contact_email && <><br /><a href={`mailto:${site.contact_email}`}>{site.contact_email}</a></>}
      {site.contact_phone && <><br />{site.contact_phone}</>}
    </p>
  );
}

/** Text message program terms. The checkbox is behind sign-in,
 * so its exact wording is quoted here for reviewers; keep it in step with shared/member/ProfileFields.tsx. */
function TextMessageTerms() {
  const { site } = useSite();
  return (
    <>
      <h2 id="text-messages">Text messages</h2>
      <p>
        {site.site_title} sends text messages about matches, events, club announcements and dues renewal reminders to
        members and applicants who check the text message box on their application or member profile. Agreeing to texts
        is optional and is not a condition of membership. The box is unchecked by default and reads:
      </p>
      <blockquote>
        <strong>Yes, text me about matches, events, and dues renewal reminders.</strong> Optional — it won't affect your
        membership. Message frequency varies. Message and data rates may apply. Reply HELP for help or STOP to any text to
        opt out, or change this anytime here. We never sell or share your number.
      </blockquote>
      <ul>
        <li>Message frequency varies, typically a few messages per month.</li>
        <li>Message and data rates may apply.</li>
        <li>Reply <strong>STOP</strong> to any message to stop receiving texts. Reply <strong>START</strong> to resume.</li>
        <li>Reply <strong>HELP</strong> for help, or contact us using the details below.</li>
        <li>Carriers are not liable for delayed or undelivered messages.</li>
      </ul>
      <p>
        You can also turn texts on or off at any time from your member profile. See our{' '}
        <Link to="/privacy">Privacy Policy</Link> for how we handle your phone number.
      </p>
    </>
  );
}

export function TermsPage() {
  usePageTitle('Terms and Conditions');
  const { site } = useSite();
  return (
    <LegalPage title="Terms and Conditions">
      <p>
        These terms apply to this website, the member portal, the online membership application and the club's text and
        email messages (together, the "services"), operated by {site.site_title} ("the club", "we", "us"). By using the
        services you agree to these terms.
      </p>

      <h2>Membership</h2>
      <p>
        Membership is granted at the discretion of the club's board. Submitting an application or paying dues does not
        guarantee membership; the board may decline, suspend or end a membership under the club's bylaws and range rules.
        Members must follow the posted <Link to="/rules">range rules</Link> at all times. You are responsible for keeping
        the information and documents you provide accurate and current.
      </p>

      <h2>Accounts</h2>
      <p>
        Keep your password private and tell us right away if you think someone else has used your account. You are
        responsible for activity under your account. We may disable an account that is misused.
      </p>

      <h2>Dues and payments</h2>
      <ul>
        <li>Dues are charged once each time you choose to pay. We never automatically bill you or store your card.</li>
        <li>Online payments are processed by Stripe. Your card details go directly to Stripe and are never sent to or stored by the club.</li>
        <li>Dues pay for membership through the club's annual renewal date shown when you pay.</li>
        <li>Dues are generally non-refundable. If you are charged in error or twice, contact us and we will refund the duplicate charge.</li>
      </ul>

      <TextMessageTerms />

      <h2>Email</h2>
      <p>
        We email you about your account, application and dues. Club newsletters and announcements include an unsubscribe
        link; account and dues notices are still sent after you unsubscribe.
      </p>

      <h2>Acceptable use</h2>
      <p>
        Do not use the services to break the law, to upload anything you don't have the right to share, to access another
        person's account or information, or to interfere with how the services run.
      </p>

      <h2>Assumption of risk</h2>
      <p>
        Shooting sports carry inherent risk. Use of the club's range and participation in club matches and events is at
        your own risk and is governed by the club's rules, waivers and bylaws, which these terms do not replace.
      </p>

      <h2>Disclaimers and limitation of liability</h2>
      <p>
        The services are provided "as is". Schedules, match results and other information may change or contain errors. To
        the fullest extent the law allows, the club and its officers and volunteers are not liable for indirect or
        consequential losses arising from use of the services.
      </p>

      <h2>Changes</h2>
      <p>
        We may update these terms. The effective date above shows when they last changed, and continued use of the
        services means you accept the updated terms. These terms are governed by the laws of the State of Kansas.
      </p>

      <h2>Contact</h2>
      <Contact />
    </LegalPage>
  );
}

export function PrivacyPage() {
  usePageTitle('Privacy Policy');
  const { site } = useSite();
  return (
    <LegalPage title="Privacy Policy">
      <p>
        This policy explains what information {site.site_title} collects through this website, the member portal and the
        online membership application, how we use it and the choices you have.
      </p>

      <h2>Information we collect</h2>
      <ul>
        <li><strong>Contact details:</strong> name, email address, mobile phone number and mailing address.</li>
        <li><strong>Membership information:</strong> NRA membership number and expiration date, application details, membership status and dues history.</li>
        <li><strong>Documents you upload:</strong> such as proof of NRA membership, a background check or a concealed carry license.</li>
        <li><strong>Payment records:</strong> the amount, date and status of each payment. Card details are collected by Stripe, not by us.</li>
        <li><strong>Messaging records:</strong> whether you agreed to texts and when, and whether our emails and texts were delivered, opened or clicked.</li>
        <li><strong>Technical information:</strong> sign-in cookies that keep you logged in, and IP address and browser type recorded for security.</li>
      </ul>

      <h2>How we use it</h2>
      <p>
        We use your information to review applications, run memberships and renewals, process dues, send account notices,
        reminders, club announcements and, if you agreed, text messages, keep the services secure, and meet our legal
        obligations. We do not sell your information or use it for advertising.
      </p>

      <h2>Text messages and your phone number</h2>
      <p>
        We text you only if you check the text message box on your application or profile, and we record when you agreed.
        Reply STOP to any text, or uncheck the box on your profile, to stop texts.{' '}
        <strong>
          We do not sell, rent or share your mobile phone number or text message consent with third parties or affiliates
          for their marketing or promotional purposes.
        </strong>{' '}
        Your number is shared only with the text message providers that deliver our messages for us. See the{' '}
        <Link to="/terms">Terms and Conditions</Link> for the full text message terms.
      </p>

      <h2>Who we share it with</h2>
      <p>Only with service providers that run parts of the services on our behalf, and only what they need:</p>
      <ul>
        <li>Stripe, to process dues payments.</li>
        <li>httpSMS, to deliver text messages.</li>
        <li>Resend, to deliver email.</li>
        <li>Render and Neon, which host our website, servers, files and database.</li>
      </ul>
      <p>
        Board members see member information as needed to run the club. We may also disclose information when required by
        law or to protect the safety of members and guests.
      </p>

      <h2>How long we keep it</h2>
      <p>
        We keep member records while you are a member and afterwards as former-member records. Uploaded membership documents
        are deleted when a membership ends. Payment records and the club's activity log are kept for the club's financial and
        audit records.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>View and update your details from the member portal.</li>
        <li>Stop texts by replying STOP or updating your profile, and stop newsletters with the unsubscribe link in any club email.</li>
        <li>Contact us to ask for a copy of your information, to correct it, or to have it deleted where we are not required to keep it.</li>
      </ul>

      <h2>Security</h2>
      <p>
        Information is sent over encrypted connections, uploaded documents are stored privately and shown only to the
        member and authorized board members, and passwords are stored only as secure hashes. No system is perfectly
        secure, so please use a strong, unique password.
      </p>

      <h2>Children</h2>
      <p>The services are intended for adults and we do not knowingly collect information from children under 13.</p>

      <h2>Changes</h2>
      <p>We may update this policy. The effective date above shows when it last changed.</p>

      <h2>Contact</h2>
      <Contact />
    </LegalPage>
  );
}
