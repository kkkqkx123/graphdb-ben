create node table Person (id INT64, PRIMARY KEY(id));
create rel table knows (FROM Person TO Person, MANY_MANY);
