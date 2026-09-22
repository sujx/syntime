export interface Envelope<T> {
  code: number;
  message: string;
  data: T;
}

export interface PageResult<T> {
  total: number;
  page: number;
  pageSize: number;
  list: T[];
}
