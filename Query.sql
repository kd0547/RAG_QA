select
    m.uid,
    m.subject,
    m.sender,
    m.received_at,
    t.status
from tasks t
join main.mails m on m.uid = t.mail_uid;