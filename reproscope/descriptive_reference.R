library(jsonlite)
bindings <- fromJSON('out/bindings.json',simplifyVector=FALSE)
results <- lapply(bindings,function(b) {
  frame <- read.csv(b$file,check.names=FALSE,na.strings=c('', ' '))
  if(length(b$filters)) for(f in b$filters) {
    values <- frame[[f$column]]
    target <- f$value
    if(is.numeric(values) && !is.null(target)) target <- as.numeric(target)
    keep <- if(f$operator=='not_missing') !is.na(values) else if(f$operator=='eq') values==target else values!=target
    frame <- frame[!is.na(keep) & keep,,drop=FALSE]
  }
  if(!is.null(b$included_ids)) frame <- frame[frame[[b$id_column]] %in% unlist(b$included_ids),,drop=FALSE]
  complete <- unlist(b$complete_on)
  if(length(complete)) frame <- frame[complete.cases(frame[,complete,drop=FALSE]),,drop=FALSE]
  columns <- unlist(b$columns)
  op <- b$operation
  analysis_n <- nrow(frame)
  value <- if(op=='n') nrow(frame) else if(op=='count_category') sum(frame[[columns[1]]]==b$category_value,na.rm=TRUE) else if(op=='count_missing') sum(is.na(frame[[columns[1]]])) else if(op=='count_threshold') {
    rule <- b$category_value
    operator <- sub('^([<>]=?).*','\\1',rule)
    threshold <- as.numeric(sub('^[<>]=?','',rule))
    values <- frame[[columns[1]]]
    sum(switch(operator, '>='=values>=threshold, '<='=values<=threshold, '>'=values>threshold, '<'=values<threshold),na.rm=TRUE)
  } else {
    cells <- frame[,columns,drop=FALSE]
    analysis_n <- sum(rowSums(!is.na(cells))>0)
    if(op=='cronbach_alpha') {
      cells <- cells[complete.cases(cells),,drop=FALSE]
      if(length(b$reverse_columns)) for(column in unlist(b$reverse_columns)) cells[[column]] <- -cells[[column]]
      analysis_n <- nrow(cells)
      covariance <- cov(cells)
      k <- ncol(cells)
      value <- k/(k-1)*(1-sum(diag(covariance))/sum(covariance))
    } else {
    values <- as.numeric(unlist(cells))
    value <- if(op=='sd') sd(values,na.rm=TRUE) else if(op=='min') min(values,na.rm=TRUE) else if(op=='max') max(values,na.rm=TRUE) else mean(values,na.rm=TRUE)
    }
    value
  }
  if(b$multiplier==100 && op %in% c('count_category','count_missing','count_threshold')) value <- value/analysis_n
  list(claim_id=b$claim_id,value=value*b$multiplier,n=analysis_n)
})
write_json(results,'out/reference_results.json',auto_unbox=TRUE,digits=17,null='null')
