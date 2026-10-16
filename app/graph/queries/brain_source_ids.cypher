// Ids of tickets and documents, so a text can mention them.
MATCH (s) WHERE s:Ticket OR s:Document
RETURN s.id AS id
