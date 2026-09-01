package org.samapr.checker;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Collectors;

public final class ApiDiffChecker {
  private static Set<String> api(CompilationUnit cu) {
    Set<String> out = new TreeSet<>();
    for (MethodDeclaration m : cu.findAll(MethodDeclaration.class)) {
      if (m.isPublic() || m.isProtected()) out.add("M|" + m.getDeclarationAsString(true, true, true));
    }
    for (ConstructorDeclaration c : cu.findAll(ConstructorDeclaration.class)) {
      if (c.isPublic() || c.isProtected()) out.add("C|" + c.getDeclarationAsString(true, true, true));
    }
    for (FieldDeclaration f : cu.findAll(FieldDeclaration.class)) {
      if (f.isPublic() || f.isProtected()) for (VariableDeclarator v : f.getVariables()) out.add("F|" + f.getModifiers() + "|" + v.getType() + "|" + v.getNameAsString());
    }
    for (TypeDeclaration<?> t : cu.findAll(TypeDeclaration.class)) if (t.isPublic() || t.isProtected()) out.add("T|" + t.getNameAsString());
    return out;
  }

  private static String methodKey(MethodDeclaration m) {
    return m.getNameAsString() + "(" + m.getParameters().stream().map(p -> p.getType().asString()).collect(Collectors.joining(",")) + ")";
  }
  private static Map<String,MethodDeclaration> methods(CompilationUnit cu) {
    Map<String,MethodDeclaration> out=new TreeMap<>();
    for(MethodDeclaration m:cu.findAll(MethodDeclaration.class)) out.put(methodKey(m),m);
    return out;
  }
  private static Set<String> astNodes(MethodDeclaration m) {
    Set<String> out=new TreeSet<>();
    for(Node n:m.findAll(Node.class)) out.add(n.getClass().getSimpleName());
    return out;
  }
  private static Set<String> imports(CompilationUnit cu) {
    return cu.getImports().stream().map(Object::toString).collect(Collectors.toCollection(TreeSet::new));
  }
  private static Set<String> fields(CompilationUnit cu) {
    return cu.findAll(FieldDeclaration.class).stream().map(Object::toString).collect(Collectors.toCollection(TreeSet::new));
  }
  private static Set<String> privateMethods(CompilationUnit cu) {
    return cu.findAll(MethodDeclaration.class).stream().filter(MethodDeclaration::isPrivate).map(ApiDiffChecker::methodKey).collect(Collectors.toCollection(TreeSet::new));
  }
  private static String esc(String s) { return s.replace("\\","\\\\").replace("\"","\\\"").replace("\r","\\r").replace("\n","\\n").replace("\t","\\t"); }
  private static String quote(String s) { return "\""+esc(s)+"\""; }
  private static String arr(Collection<String> xs) { return xs.stream().map(ApiDiffChecker::quote).collect(Collectors.joining(",", "[", "]")); }

  private static String changedMethods(CompilationUnit before, CompilationUnit after) {
    Map<String,MethodDeclaration> a=methods(before), b=methods(after); Set<String> keys=new TreeSet<>(); keys.addAll(a.keySet()); keys.addAll(b.keySet());
    List<String> rows=new ArrayList<>();
    for(String key:keys) {
      MethodDeclaration old=a.get(key), cur=b.get(key); String oldSource=old==null?"":old.toString(), newSource=cur==null?"":cur.toString();
      if(oldSource.equals(newSource)) continue;
      String name=cur!=null?cur.getNameAsString():old.getNameAsString(); Set<String> nodes=cur!=null?astNodes(cur):Collections.emptySet();
      String status=old==null?"added":cur==null?"removed":"modified";
      rows.add("{\"key\":"+quote(key)+",\"name\":"+quote(name)+",\"status\":"+quote(status)+",\"ast_nodes\":"+arr(nodes)+",\"before_source\":"+quote(oldSource)+",\"after_source\":"+quote(newSource)+"}");
    }
    return rows.stream().collect(Collectors.joining(",", "[", "]"));
  }

  public static void main(String[] args) throws Exception {
    Map<String,String> a=new HashMap<>(); for(int i=0;i+1<args.length;i+=2)a.put(args[i],args[i+1]);
    if(!a.containsKey("--before")||!a.containsKey("--after")||!a.containsKey("--out")){System.err.println("Usage: --before FILE --after FILE --out JSON");System.exit(2);}
    CompilationUnit before=StaticJavaParser.parse(Paths.get(a.get("--before"))), after=StaticJavaParser.parse(Paths.get(a.get("--after")));
    Set<String> beforeApi=api(before), afterApi=api(after); Set<String> added=new TreeSet<>(afterApi); added.removeAll(beforeApi); Set<String> removed=new TreeSet<>(beforeApi); removed.removeAll(afterApi);
    Set<String> addedPrivate=privateMethods(after); addedPrivate.removeAll(privateMethods(before)); boolean unchanged=added.isEmpty()&&removed.isEmpty();
    String json="{\n"+
      "  \"status\": \"ok\",\n"+
      "  \"unchanged\": "+unchanged+",\n"+
      "  \"added\": "+arr(added)+",\n"+
      "  \"removed\": "+arr(removed)+",\n"+
      "  \"imports_changed\": "+(!imports(before).equals(imports(after)))+",\n"+
      "  \"fields_changed\": "+(!fields(before).equals(fields(after)))+",\n"+
      "  \"added_private_methods\": "+arr(addedPrivate)+",\n"+
      "  \"changed_methods\": "+changedMethods(before,after)+"\n"+
      "}\n";
    Files.writeString(Paths.get(a.get("--out")),json,StandardCharsets.UTF_8); if(!unchanged)System.exit(3);
  }
}
